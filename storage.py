import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager


SCHEMA = '''
CREATE TABLE IF NOT EXISTS nurses (
 id TEXT PRIMARY KEY, nurse_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 email TEXT UNIQUE NOT NULL, phone TEXT NOT NULL, password_hash TEXT NOT NULL,
 photo BLOB NOT NULL, id_card BLOB NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, nurse_id TEXT NOT NULL REFERENCES nurses(id), expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patients (
 id TEXT PRIMARY KEY, nurse_id TEXT NOT NULL REFERENCES nurses(id), name TEXT NOT NULL,
 age INTEGER NOT NULL, bed TEXT NOT NULL, created_at REAL NOT NULL,
 connected INTEGER NOT NULL DEFAULT 1, removed_at REAL, last_status TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS active_beds ON patients(bed COLLATE NOCASE) WHERE removed_at IS NULL;
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nurse_id TEXT NOT NULL REFERENCES nurses(id),
 patient_id TEXT NOT NULL REFERENCES patients(id), kind TEXT NOT NULL,
 old_status TEXT, new_status TEXT, occurred_at REAL NOT NULL, acknowledged_at REAL);
CREATE INDEX IF NOT EXISTS events_owner ON events(nurse_id,id);
CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, seen_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts (
 key TEXT PRIMARY KEY, failures INTEGER NOT NULL, updated_at REAL NOT NULL, locked_until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.migration_backup = None
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nurses'").fetchone()
            legacy = existing and 'role' not in {r['name'] for r in db.execute('PRAGMA table_info(nurses)')}
            if legacy:
                backup = self.path.with_name(f'hospital.before_roles_{time.time_ns()}.sqlite3')
                with sqlite3.connect(backup) as target:
                    db.backup(target)
                self.migration_backup = backup
            db.executescript(SCHEMA)
            db.execute('BEGIN IMMEDIATE')
            additions = {
                'nurses': [('role', "TEXT NOT NULL DEFAULT 'nurse'"),
                           ('doctor_id', 'TEXT REFERENCES nurses(id)'),
                           ('approval_status', "TEXT NOT NULL DEFAULT 'unassigned'"),
                           ('reviewed_at', 'REAL')],
                'patients': [('doctor_id', 'TEXT REFERENCES nurses(id)')],
                'events': [('actor_id', 'TEXT REFERENCES nurses(id)'),
                           ('acknowledged_by', 'TEXT REFERENCES nurses(id)')]
            }
            for table, fields in additions.items():
                columns = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
                for name, spec in fields:
                    if name not in columns:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {spec}')
            db.execute('''CREATE TABLE IF NOT EXISTS staff_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT REFERENCES nurses(id),
                subject_id TEXT NOT NULL REFERENCES nurses(id), action TEXT NOT NULL, occurred_at REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS patients_team ON patients(doctor_id)')
            db.execute('CREATE INDEX IF NOT EXISTS nurses_team ON nurses(doctor_id,approval_status)')
            db.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','3')")
            if legacy:
                db.execute('DELETE FROM sessions')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def consume(self, request_id):
        with self.connect() as db:
            db.execute('DELETE FROM requests WHERE seen_at < ?', (time.time() - 180,))
            try:
                db.execute('INSERT INTO requests VALUES (?,?)', (request_id, time.time()))
            except sqlite3.IntegrityError as exc:
                raise ValueError('Duplicate request') from exc

    @staticmethod
    def event(db, patient, kind, old=None, new=None, actor_id=None):
        db.execute('INSERT INTO events(nurse_id,patient_id,kind,old_status,new_status,occurred_at,actor_id) VALUES(?,?,?,?,?,?,?)',
                   (patient['nurse_id'], patient['id'], kind, old, new, time.time(), actor_id))

    @staticmethod
    def audit(db, actor_id, subject_id, action):
        db.execute('INSERT INTO staff_audit(actor_id,subject_id,action,occurred_at) VALUES(?,?,?,?)',
                   (actor_id, subject_id, action, time.time()))

    def active(self):
        with self.connect() as db:
            return [dict(p) for p in db.execute('SELECT * FROM patients WHERE removed_at IS NULL AND doctor_id IS NOT NULL')]

    def record_status(self, patient_id, status):
        """Persist only a status transition, never a reading or reconstruction score."""
        if status not in {'NORMAL', 'ELEVATED', 'CRITICAL'}:
            raise ValueError('Invalid model status')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = db.execute('SELECT * FROM patients WHERE id=? AND removed_at IS NULL AND connected=1', (patient_id,)).fetchone()
            if p is None:
                return False
            old = p['last_status']
            if old != status:
                if status != 'NORMAL' or old in {'ELEVATED', 'CRITICAL'}:
                    self.event(db, p, 'RETURNED_NORMAL' if status == 'NORMAL' else status, old, status)
                db.execute('UPDATE patients SET last_status=? WHERE id=?', (status, patient_id))
            return True


class BackendLock:
    """Only one backend owns the in-memory readings and simulator for this DB."""
    def __init__(self, path):
        self.path = path
        self.file = None

    def acquire(self):
        import os
        self.file = open(self.path, 'a+b')
        self.file.seek(0)
        if self.file.read(1) == b'':
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close(); self.file = None
            raise RuntimeError('Another backend owns this database. Use one Uvicorn worker and no --reload.') from exc

    def release(self):
        if self.file:
            self.file.close(); self.file = None
