import base64
import json
import os
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DOMAINS = {'request', 'response', 'centre_request', 'centre_response', 'profile'}


def cipher(key, domain):
    if domain not in DOMAINS:
        raise ValueError('Invalid encryption domain')
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                   info=f'pulseward-v2/{domain}'.encode()).derive(key)
    return AESGCM(derived)


def encrypt(payload, key, domain):
    nonce = os.urandom(12)
    raw = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
    data = cipher(key, domain).encrypt(nonce, raw, domain.encode())
    return {'nonce': base64.b64encode(nonce).decode(), 'ciphertext': base64.b64encode(data).decode()}


def decrypt(envelope, key, domain):
    nonce = base64.b64decode(envelope['nonce'], validate=True)
    data = base64.b64decode(envelope['ciphertext'], validate=True)
    if len(nonce) != 12 or len(data) > 8_000_000:
        raise ValueError('Invalid encrypted packet')
    value = json.loads(cipher(key, domain).decrypt(nonce, data, domain.encode()))
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    return value


def check_fresh(timestamp):
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError('Invalid timestamp')
    if not -10 <= time.time() - timestamp <= 120:
        raise ValueError('Expired packet or clock mismatch')


def seal_image(raw, key, owner, kind):
    nonce = os.urandom(12)
    return nonce + cipher(key, 'profile').encrypt(nonce, raw, f'{owner}/{kind}'.encode())


def open_image(blob, key, owner, kind):
    return cipher(key, 'profile').decrypt(blob[:12], blob[12:], f'{owner}/{kind}'.encode())
