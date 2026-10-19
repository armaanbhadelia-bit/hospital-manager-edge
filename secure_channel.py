"""Authenticated payload encryption with separate request/response keys."""
import base64
import json
import os
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_AGE_SECONDS = 120


def cipher(key, direction):
    if direction not in {'request', 'response'}:
        raise ValueError('Invalid direction')
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                   info=f'hospital-monitor-v1/{direction}'.encode()).derive(key)
    return AESGCM(derived)


def encrypt(payload, key, direction):
    nonce = os.urandom(12)
    aad = f'hospital-monitor-v1/{direction}'.encode()
    data = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
    encrypted = cipher(key, direction).encrypt(nonce, data, aad)
    return {'nonce': base64.b64encode(nonce).decode(),
            'ciphertext': base64.b64encode(encrypted).decode()}


def decrypt(envelope, key, direction):
    nonce = base64.b64decode(envelope['nonce'], validate=True)
    ciphertext = base64.b64decode(envelope['ciphertext'], validate=True)
    if len(nonce) != 12 or len(ciphertext) > 16384:
        raise ValueError('Invalid encrypted message')
    aad = f'hospital-monitor-v1/{direction}'.encode()
    data = cipher(key, direction).decrypt(nonce, ciphertext, aad)
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Expected an object')
    return result


def check_fresh(timestamp):
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError('Invalid timestamp')
    # NaN and infinity also fail this bounded comparison.
    if not -10 <= time.time() - timestamp <= MAX_AGE_SECONDS:
        raise ValueError('Expired message or clock mismatch')
