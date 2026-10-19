import base64
import os
import re
import secrets
import sqlite3
import time
import uuid
from security import clean_image, hash_password, token_hash, verify_password
from secure_channel import open_image, seal_image


class UserError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Accounts:
    def __init__(self, store, key):
        self.store, self.key = store, key
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    def signup(self, data):
        photo, card = clean_image(data.photo), clean_image(data.id_card)
        uid = str(uuid.uuid4())
        digest = hash_password(data.password)
        try:
            with self.store.connect() as db:
                if data.staff_id == '__OWNER__':
                    raise UserError('That staff ID is reserved.')
                doctor_id = None
                if data.role == 'nurse':
                    doctor_id = self.find_doctor(db, data.doctor_id)
                elif data.doctor_id:
                    raise UserError('Doctors do not join another doctor during signup.')
                db.execute('''INSERT INTO nurses(id,nurse_id,name,email,phone,password_hash,photo,id_card,created_at,
                    role,doctor_id,approval_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (uid, data.staff_id, data.name, data.email, data.phone, digest,
                            seal_image(photo, self.key, uid, 'photo'), seal_image(card, self.key, uid, 'id_card'), time.time(),
                            data.role, doctor_id, 'pending' if data.role == 'nurse' else 'approved'))
                if data.role == 'nurse':
                    self.store.audit(db, uid, uid, 'TEAM_REQUESTED')
        except sqlite3.IntegrityError:
            raise UserError('That email or staff ID is already registered.', 409) from None
        return {'message': 'Account created. You can now log in.', 'approval_status': 'pending' if doctor_id else 'approved'}

    @staticmethod
    def find_doctor(db, staff_id):
        doctor = db.execute("SELECT id FROM nurses WHERE nurse_id=? AND role='doctor'", ((staff_id or '').strip().upper(),)).fetchone()
        if doctor is None:
            raise UserError('Doctor ID not found. Ask your doctor for their registered ID.')
        return doctor['id']

    def configure_admin(self):
        email = os.getenv('HOSPITAL_ADMIN_EMAIL', '').strip().lower()
        digest = os.getenv('HOSPITAL_ADMIN_PASSWORD_HASH', '')
        if not email and not digest:
            return
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or not digest.startswith('scrypt$'):
            raise RuntimeError('Run python setup_admin.py to configure the owner account.')
        with self.store.connect() as db:
            other = db.execute("SELECT id FROM nurses WHERE email=? AND id<>'pulseward-owner'", (email,)).fetchone()
            if other:
                raise RuntimeError('Owner email is already used by a staff account. Choose another email with setup_admin.py.')
            current = db.execute("SELECT * FROM nurses WHERE id='pulseward-owner'").fetchone()
            if current:
                if current['email'] != email or current['password_hash'] != digest:
                    db.execute("UPDATE nurses SET email=?,password_hash=? WHERE id='pulseward-owner'", (email, digest))
                    db.execute("DELETE FROM sessions WHERE nurse_id='pulseward-owner'")
            else:
                db.execute('''INSERT INTO nurses(id,nurse_id,name,email,phone,password_hash,photo,id_card,created_at,role,approval_status)
                    VALUES(?,?,?,?,?,?,?,?,?,'admin','approved')''',
                           ('pulseward-owner', '__OWNER__', 'Hospital owner', email, '', digest, b'', b'', time.time()))

    def request_team(self, actor, doctor_staff_id):
        if actor['role'] != 'nurse':
            raise UserError('Only nurses request team membership.', 403)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM nurses WHERE id=?', (actor['id'],)).fetchone()
            if current['approval_status'] in {'approved', 'pending'}:
                raise UserError('You already have an approved or pending team assignment.', 409)
            doctor_id = self.find_doctor(db, doctor_staff_id)
            db.execute("UPDATE nurses SET doctor_id=?,approval_status='pending',reviewed_at=NULL WHERE id=?", (doctor_id, actor['id']))
            self.store.audit(db, actor['id'], actor['id'], 'TEAM_REQUESTED')
        return {}

    def check_password(self, bucket, password, digest):
        # Serialize attempts across threads; failed attempts commit before raising.
        now = time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_attempts WHERE updated_at < ?', (now - 86400,))
            row = db.execute('SELECT * FROM auth_attempts WHERE key=?', (bucket,)).fetchone()
            if row and row['locked_until'] > now:
                raise UserError('Too many attempts. Try again in a few minutes.', 429)
            valid = verify_password(password, digest)
            if valid:
                db.execute('DELETE FROM auth_attempts WHERE key=?', (bucket,))
            else:
                failures = row['failures'] + 1 if row and now - row['updated_at'] < 600 else 1
                # After a completed lock period, start a new set of attempts.
                if row and row['locked_until'] and row['locked_until'] <= now:
                    failures = 1
                lock_until = now + 300 if failures >= 5 else 0
                db.execute('INSERT OR REPLACE INTO auth_attempts VALUES(?,?,?,?)', (bucket, failures, now, lock_until))
        return valid

    def login(self, data):
        email = data.email.strip().lower()
        with self.store.connect() as db:
            nurse = db.execute('SELECT * FROM nurses WHERE email=?', (email,)).fetchone()
        valid = self.check_password('login:' + token_hash(email), data.password,
                                    nurse['password_hash'] if nurse else self.dummy_hash)
        if not valid or nurse is None:
            raise UserError('Email or password is incorrect.', 401)
        token = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires_at < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(token), nurse['id'], time.time() + 8 * 3600))
        return {'session': token, 'profile': self.public_profile(nurse)}

    def require(self, token):
        if not token:
            raise UserError('Please log in.', 401)
        with self.store.connect() as db:
            nurse = db.execute('SELECT n.* FROM nurses n JOIN sessions s ON s.nurse_id=n.id WHERE s.token_hash=? AND s.expires_at>?',
                               (token_hash(token), time.time())).fetchone()
        if nurse is None:
            raise UserError('Your session has ended. Please log in again.', 401)
        return dict(nurse)

    def confirm(self, nurse, password):
        if not self.check_password('confirm:' + nurse['id'], password, nurse['password_hash']):
            raise UserError('Password confirmation failed.', 403)

    def logout(self, token):
        with self.store.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))
        return {}

    def public_profile(self, nurse, include_card=False):
        result = {k: nurse[k] for k in ['name', 'email', 'phone', 'role', 'approval_status']}
        result['staff_id'] = nurse['nurse_id']
        result['account_id'] = nurse['id']
        result['doctor_name'] = result['doctor_staff_id'] = None
        if nurse['doctor_id']:
            with self.store.connect() as db:
                doctor = db.execute('SELECT name,nurse_id FROM nurses WHERE id=?', (nurse['doctor_id'],)).fetchone()
            if doctor:
                result['doctor_name'], result['doctor_staff_id'] = doctor['name'], doctor['nurse_id']
        result['photo'] = base64.b64encode(open_image(nurse['photo'], self.key, nurse['id'], 'photo')).decode() if nurse['photo'] else None
        if include_card and nurse['id_card']:
            result['id_card'] = base64.b64encode(open_image(nurse['id_card'], self.key, nurse['id'], 'id_card')).decode()
        return result
