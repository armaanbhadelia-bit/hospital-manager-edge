"""Generate local development secrets once; never print them."""
import base64
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parent / '.env'
if path.exists():
    print('.env already exists. Existing configuration was kept.')
else:
    key = base64.b64encode(os.urandom(32)).decode()
    token = secrets.token_urlsafe(32)
    with path.open('x', encoding='utf-8') as f:
        f.write(f'HOSPITAL_MASTER_KEY={key}\nHOSPITAL_API_TOKEN={token}\n'
                'HOSPITAL_API_URL=http://127.0.0.1:8000\n')
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print('Local configuration created. Start FastAPI and Streamlit next.')
