import base64
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')


def master_key():
    try:
        key = base64.b64decode(os.environ['HOSPITAL_MASTER_KEY'], validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except (KeyError, ValueError) as exc:
        raise RuntimeError('Run python setup_local.py before starting the app.') from exc


def api_token():
    token = os.getenv('HOSPITAL_API_TOKEN', '')
    if len(token) < 32:
        raise RuntimeError('Run python setup_local.py before starting the app.')
    return token


def api_url():
    url = os.getenv('HOSPITAL_API_URL', 'http://127.0.0.1:8000').rstrip('/')
    parsed = urlsplit(url)
    local = parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('Use a base API URL without credentials or query parameters.')
    if not parsed.hostname or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')):
        raise RuntimeError('Remote connections require HTTPS.')
    return url


def data_dir():
    path = Path(os.getenv('HOSPITAL_DATA_DIR', str(ROOT / 'data'))).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
