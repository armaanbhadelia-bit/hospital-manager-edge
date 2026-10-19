"""Run with: python -m uvicorn server:app --host 127.0.0.1 --port 8000"""
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from config import ROOT, api_token, master_key
from inference import Predictor
from secure_channel import check_fresh, decrypt, encrypt


class Vitals(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    # Input validity bounds, NOT clinical alert thresholds.
    heart_rate: float = Field(ge=0, le=350)
    oxygen_saturation: float = Field(ge=0, le=100)
    respiratory_rate: float = Field(ge=0, le=150)
    age: int = Field(ge=0, le=130)


class Reading(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    request_id: UUID
    patient_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    node_id: str = Field(min_length=1, max_length=64)
    sent_at: float
    measured_at: float
    vitals: Vitals


class Envelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nonce: str = Field(min_length=16, max_length=16)
    ciphertext: str = Field(min_length=24, max_length=24000)


def consume_request(database, request_id):
    """Atomic persistent replay check, also shared across local workers."""
    with sqlite3.connect(database, timeout=5) as db:
        db.execute('DELETE FROM requests WHERE seen_at < ?', (time.time() - 180,))
        try:
            db.execute('INSERT INTO requests VALUES (?, ?)', (request_id, time.time()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, 'Request already processed') from exc


@asynccontextmanager
async def lifespan(app):
    app.state.key = master_key()
    app.state.token = api_token()
    app.state.predictor = Predictor(ROOT / 'telemetry_autoencoder.pth')
    app.state.database = ROOT / 'replay.sqlite3'
    with sqlite3.connect(app.state.database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, seen_at REAL)')
    yield


app = FastAPI(title='Hospital Monitor — encrypted inference', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ready'}


@app.post('/predict/encrypted', response_model=Envelope)
def predict(envelope: Envelope, authorization: Annotated[str | None, Header()] = None):
    expected = 'Bearer ' + app.state.token
    if not secrets.compare_digest((authorization or '').encode(), expected.encode()):
        raise HTTPException(401, 'Unauthorized')
    try:
        reading = Reading.model_validate(decrypt(envelope.model_dump(), app.state.key, 'request'))
        check_fresh(reading.sent_at)
        check_fresh(reading.measured_at)
    except (InvalidTag, ValueError, KeyError, TypeError, ValidationError):
        raise HTTPException(400, 'Invalid, expired, or unauthenticated reading') from None
    consume_request(app.state.database, str(reading.request_id))
    result = app.state.predictor.predict(reading.vitals)
    payload = {'request_id': str(reading.request_id), 'patient_id': reading.patient_id,
               'processed_at': time.time(), **result}
    return encrypt(payload, app.state.key, 'response')
