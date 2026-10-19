"""Hospital-centre sender; reusable by a future IoMT adapter."""
import time
import uuid
import requests
from config import api_token, api_url, master_key
from secure_channel import check_fresh, decrypt, encrypt


def send_reading(patient_id, vitals, measured_at=None):
    key = master_key()
    request_id = str(uuid.uuid4())
    payload = {'request_id': request_id, 'patient_id': patient_id,
               'node_id': 'hospital-centre-01', 'sent_at': time.time(),
               'measured_at': time.time() if measured_at is None else measured_at,
               'vitals': vitals}
    envelope = encrypt(payload, key, 'request')
    response = requests.post(api_url() + '/predict/encrypted', json=envelope,
                             headers={'Authorization': 'Bearer ' + api_token()},
                             timeout=(2, 5), allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f'Inference service returned HTTP {response.status_code}')
    result = decrypt(response.json(), key, 'response')
    if result.get('request_id') != request_id or result.get('patient_id') != patient_id:
        raise ValueError('Response does not match this reading')
    check_fresh(result.get('processed_at'))
    if result.get('status') not in {'NORMAL', 'ELEVATED', 'CRITICAL'}:
        raise ValueError('Unrecognized model status')
    return result
