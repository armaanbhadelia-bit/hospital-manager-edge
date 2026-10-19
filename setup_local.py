"""Create missing configuration without changing existing secrets."""
import base64
import os
import secrets
from pathlib import Path
from dotenv import dotenv_values


def main():
    path = Path(__file__).resolve().parent / '.env'
    existing = dotenv_values(path) if path.exists() else {}
    missing = {}
    if not existing.get('HOSPITAL_MASTER_KEY'):
        if (path.parent / 'data' / 'hospital.sqlite3').exists():
            raise SystemExit('Existing database found but its key is missing. Restore the original .env; do not replace its key.')
        missing['HOSPITAL_MASTER_KEY'] = base64.b64encode(os.urandom(32)).decode()
    if not existing.get('HOSPITAL_API_TOKEN'):
        missing['HOSPITAL_API_TOKEN'] = secrets.token_urlsafe(32)
    if not existing.get('HOSPITAL_API_URL'):
        missing['HOSPITAL_API_URL'] = 'http://127.0.0.1:8000'
    if missing:
        with path.open('a', encoding='utf-8') as f:
            f.write('\n' + ''.join(f'{k}={v}\n' for k, v in missing.items()))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        print('Configuration ready. Existing values were preserved; missing values were added.')
    else:
        print('Configuration already exists. No changes needed.')
    print('Next: python -m uvicorn server:app --host 127.0.0.1 --port 8000')


if __name__ == '__main__':
    main()
