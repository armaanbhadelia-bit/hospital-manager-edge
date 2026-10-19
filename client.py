import math
import time
import uuid
import requests
from config import api_token, api_url, master_key
from secure_channel import check_fresh, decrypt, encrypt


class APIError(Exception):
    def __init__(self, message, code=503):
        super().__init__(message)
        self.code = code


def exchange(path, payload, request_domain, response_domain):
    key = master_key()
    try:
        response = requests.post(api_url() + path, json=encrypt(payload, key, request_domain),
                                 headers={'Authorization': 'Bearer ' + api_token()},
                                 timeout=(2, 8), allow_redirects=False)
        if response.status_code != 200:
            raise APIError('Service request failed. Check the backend and configuration.', response.status_code)
        value = decrypt(response.json(), key, response_domain)
        check_fresh(value.get('processed_at'))
        if value.get('request_id') != payload['request_id']:
            raise ValueError('Response mismatch')
        return value
    except APIError:
        raise
    except Exception:
        raise APIError('Cannot reach or verify the backend. Keep FastAPI running and check the shared configuration.') from None


def call(action, data=None, session=None):
    payload = {'request_id': str(uuid.uuid4()), 'sent_at': time.time(),
               'action': action, 'session': session, 'data': {} if data is None else data}
    reply = exchange('/centre/encrypted', payload, 'centre_request', 'centre_response')
    if not reply.get('ok'):
        raise APIError(reply.get('error', 'Request failed.'), reply.get('code', 400))
    return reply['data']


def send_reading(patient_id, vitals, measured_at):
    payload = {'request_id': str(uuid.uuid4()), 'patient_id': patient_id,
               'sent_at': time.time(), 'measured_at': measured_at, 'vitals': vitals}
    result = exchange('/predict/encrypted', payload, 'request', 'response')
    if result.get('patient_id') != patient_id or result.get('status') not in {'NORMAL', 'ELEVATED', 'CRITICAL'}:
        raise APIError('Prediction response mismatch.')
    score = result.get('mse_loss')
    if not isinstance(score, (float, int)) or not math.isfinite(score) or score < 0:
        raise APIError('Invalid model score.')
    return result
