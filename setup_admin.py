"""Configure the single read-only owner account. Run locally, with backend stopped."""
import getpass
import re
from dotenv import set_key
from config import ROOT
from security import hash_password


def main():
    path = ROOT / '.env'
    if not path.exists():
        raise SystemExit('Run setup_local.py first. Keep an existing .env if upgrading.')
    print('Configure the read-only hospital owner. Use an email not used by a doctor/nurse.')
    email = input('Owner email: ').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise SystemExit('Enter a valid email address.')
    password = getpass.getpass('Owner password (10–128 characters): ')
    confirm = getpass.getpass('Confirm password: ')
    if not 10 <= len(password) <= 128 or password != confirm:
        raise SystemExit('Passwords must match and contain 10–128 characters.')
    set_key(str(path), 'HOSPITAL_ADMIN_EMAIL', email)
    set_key(str(path), 'HOSPITAL_ADMIN_PASSWORD_HASH', hash_password(password))
    print('Owner credentials configured. Existing encryption keys were preserved.')
    print('Restart FastAPI, then log in with this email and password. No admin signup is exposed.')


if __name__ == '__main__':
    main()
