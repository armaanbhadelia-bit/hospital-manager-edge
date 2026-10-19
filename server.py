"""One local FastAPI worker owns accounts, the simulator and LSTM inference."""
import asyncio
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated

from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from accounts import Accounts, UserError
from config import ROOT, api_token, data_dir, master_key
from inference import Predictor
from schemas import Command, Envelope, Reading
from secure_channel import check_fresh, decrypt, encrypt
from service import NurseService
from simulator import Engine
from storage import BackendLock, Store


def create_app(start_simulator=True):
    @asynccontextmanager
    async def lifespan(app):
        key = master_key()
        token = api_token()
        folder = data_dir()
        lock = BackendLock(folder / 'backend.lock')
        lock.acquire()
        engine = None
        try:
            store = Store(folder / 'hospital.sqlite3')
            fingerprint = hmac.new(key, b'pulseward-db-key-check', hashlib.sha256).hexdigest()
            with store.connect() as db:
                saved = db.execute("SELECT value FROM metadata WHERE key='key_fingerprint'").fetchone()
                if saved and not hmac.compare_digest(saved['value'], fingerprint):
                    raise RuntimeError('The encryption key does not match this database. Restore its original .env.')
                db.execute("INSERT OR IGNORE INTO metadata VALUES('key_fingerprint',?)", (fingerprint,))
            predictor = Predictor(ROOT / 'telemetry_autoencoder.pth')
            engine = Engine(store)
            app.state.key, app.state.token = key, token
            app.state.store, app.state.engine, app.state.predictor = store, engine, predictor
            accounts = Accounts(store, key)
            accounts.configure_admin()
            app.state.service = NurseService(store, accounts, engine)
            if start_simulator:
                engine.start()
            yield
        finally:
            if engine:
                await asyncio.to_thread(engine.stop)
            lock.release()

    app = FastAPI(title='PulseWard v3 — doctor teams', lifespan=lifespan)

    @app.middleware('http')
    async def bound_body(request: Request, call_next):
        if request.method == 'POST':
            try:
                size = int(request.headers.get('content-length', '-1'))
            except ValueError:
                size = -1
            if size < 0 or size > 12_000_000:
                return JSONResponse({'detail': 'Missing or oversized request length'}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Default validation responses can echo sensitive inputs. Never do that.
        return JSONResponse({'detail': 'Invalid encrypted request format'}, status_code=422)

    def authorize(authorization):
        if not secrets.compare_digest((authorization or '').encode(), ('Bearer ' + app.state.token).encode()):
            raise HTTPException(401, 'Unauthorized')

    def unpack(envelope, domain, schema):
        try:
            payload = schema.model_validate(decrypt(envelope.model_dump(), app.state.key, domain))
            check_fresh(payload.sent_at)
        except (InvalidTag, ValueError, KeyError, TypeError):
            raise HTTPException(400, 'Invalid or expired encrypted request') from None
        try:
            app.state.store.consume(str(payload.request_id))
        except ValueError:
            raise HTTPException(409, 'Duplicate request') from None
        return payload

    @app.get('/health')
    def health():
        return {'status': 'ready', 'version': '3.0'}

    @app.post('/predict/encrypted', response_model=Envelope)
    def predict(envelope: Envelope, authorization: Annotated[str | None, Header()] = None):
        authorize(authorization)
        reading = unpack(envelope, 'request', Reading)
        try:
            check_fresh(reading.measured_at)
        except ValueError:
            raise HTTPException(400, 'Expired reading') from None
        try:
            result = app.state.predictor.predict(reading.vitals)
        except Exception:
            raise HTTPException(503, 'Inference unavailable') from None
        return encrypt({'request_id': str(reading.request_id), 'patient_id': reading.patient_id,
                        'processed_at': time.time(), **result}, app.state.key, 'response')

    @app.post('/centre/encrypted', response_model=Envelope)
    def centre(envelope: Envelope, authorization: Annotated[str | None, Header()] = None):
        authorize(authorization)
        command = unpack(envelope, 'centre_request', Command)
        reply = {'request_id': str(command.request_id), 'processed_at': time.time()}
        try:
            data = app.state.service.handle(command.action, command.data, command.session)
            reply.update(ok=True, data=data)
        except UserError as exc:
            reply.update(ok=False, error=str(exc), code=exc.code)
        except ValidationError as exc:
            fields = ', '.join('.'.join(str(v) for v in e['loc']) for e in exc.errors())
            reply.update(ok=False, error='Check these fields: ' + fields, code=422)
        except ValueError as exc:
            # Only controlled image validation errors are exposed here.
            reply.update(ok=False, error='Invalid image or input. Use PNG/JPEG images under 2 MB.', code=400)
        except Exception:
            reply.update(ok=False, error='The operation could not be completed. Please try again.', code=500)
        reply['processed_at'] = time.time()
        return encrypt(reply, app.state.key, 'centre_response')

    return app


app = create_app()
