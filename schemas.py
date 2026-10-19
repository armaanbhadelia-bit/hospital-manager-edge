import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=False)


class Signup(Strict):
    role: Literal['doctor', 'nurse']
    name: str = Field(min_length=2, max_length=80)
    staff_id: str = Field(min_length=2, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    doctor_id: str | None = Field(default=None, max_length=40)
    email: str = Field(min_length=3, max_length=254)
    phone: str = Field(min_length=7, max_length=24)
    password: str = Field(min_length=10, max_length=128)
    photo: str = Field(min_length=1, max_length=2_700_000)
    id_card: str = Field(min_length=1, max_length=2_700_000)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('Enter a full name')
        return value

    @field_validator('staff_id')
    @classmethod
    def normalize_id(cls, value):
        return value.upper()

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        if not re.fullmatch(r'\+?[0-9 ()-]+', value) or not 7 <= len(re.sub(r'\D', '', value)) <= 15:
            raise ValueError('Enter a valid phone number')
        return value.strip()


class Login(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AddPatient(Strict):
    name: str = Field(min_length=1, max_length=80)
    age: int = Field(ge=18, le=100)
    bed: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('name', 'bed')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('This field cannot be blank')
        return value.strip()


class RemovePatient(Strict):
    patient_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Device(Strict):
    patient_id: str = Field(min_length=1, max_length=64)
    connected: bool


class Ack(Strict):
    event_id: int = Field(gt=0)


class Events(Strict):
    before_id: int | None = Field(default=None, gt=0)


class Empty(Strict):
    pass


class TeamRequest(Strict):
    doctor_id: str = Field(min_length=2, max_length=40)


class ReviewNurse(Strict):
    account_id: str = Field(min_length=1, max_length=64)
    decision: Literal['approve', 'reject']


class NurseRequest(Strict):
    account_id: str = Field(min_length=1, max_length=64)


class Vitals(Strict):
    heart_rate: float = Field(ge=0, le=350)
    oxygen_saturation: float = Field(ge=0, le=100)
    respiratory_rate: float = Field(ge=0, le=150)
    age: int = Field(ge=18, le=100)


class Reading(Strict):
    request_id: UUID
    patient_id: str = Field(min_length=1, max_length=64)
    measured_at: float
    sent_at: float
    vitals: Vitals


class Envelope(Strict):
    nonce: str = Field(min_length=16, max_length=16)
    ciphertext: str = Field(min_length=24, max_length=10_700_000)


class Command(Strict):
    request_id: UUID
    sent_at: float
    action: str = Field(min_length=1, max_length=32)
    session: str | None = Field(default=None, max_length=256)
    data: dict
