import sqlite3
import time
import uuid
from accounts import UserError
from alert_rules import ACK_SQL, needs_ack
from schemas import (Ack, AddPatient, Device, Empty, Events, Login, RemovePatient,
                     Signup, TeamRequest, ReviewNurse, NurseRequest)


class NurseService:
    """Role-aware service; class name retained for compatibility with server.py."""
    def __init__(self, store, accounts, engine):
        self.store, self.accounts, self.engine = store, accounts, engine

    @staticmethod
    def team_id(actor):
        if actor['role'] == 'doctor':
            return actor['id']
        if actor['role'] == 'nurse' and actor['approval_status'] == 'approved' and actor['doctor_id']:
            return actor['doctor_id']
        raise UserError('An approved doctor-team membership is required.', 403)

    @staticmethod
    def require_role(actor, role):
        if actor['role'] != role:
            raise UserError('You do not have permission for this action.', 403)

    def handle(self, action, data, session):
        definitions = {'signup': Signup, 'login': Login, 'logout': Empty, 'profile': Empty,
                       'account_state': Empty, 'dashboard': Empty, 'add_patient': AddPatient,
                       'remove_patient': RemovePatient, 'device': Device, 'acknowledge': Ack,
                       'events': Events, 'request_team': TeamRequest, 'team': Empty,
                       'nurse_request': NurseRequest, 'review_nurse': ReviewNurse,
                       'admin_overview': Empty, 'admin_events': Events, 'admin_audit': Events}
        if action not in definitions:
            raise UserError('Unknown action.', 404)
        payload = definitions[action].model_validate(data)
        if action == 'signup':
            return self.accounts.signup(payload)
        if action == 'login':
            return self.accounts.login(payload)
        actor = self.accounts.require(session)
        if action == 'logout':
            return self.accounts.logout(session)
        if action == 'profile':
            return self.accounts.public_profile(actor, include_card=True)
        if action == 'account_state':
            return {k: actor[k] for k in ['role', 'approval_status', 'name']}
        if actor['role'] == 'admin':
            if action == 'admin_overview':
                return self.admin_overview()
            if action == 'admin_events':
                return self.events(actor, payload.before_id)
            if action == 'admin_audit':
                return self.admin_audit(payload.before_id)
            raise UserError('The owner portal is read-only.', 403)
        if action.startswith('admin_'):
            raise UserError('Owner access is required.', 403)
        if action == 'request_team':
            return self.accounts.request_team(actor, payload.doctor_id)
        if action == 'team':
            return self.team(actor)
        if action == 'nurse_request':
            return self.nurse_request(actor, payload.account_id)
        if action == 'review_nurse':
            return self.review_nurse(actor, payload)
        self.team_id(actor)  # All patient operations require approved membership.
        if action == 'dashboard':
            return self.dashboard(actor)
        if action == 'add_patient':
            return self.add(actor, payload)
        if action == 'remove_patient':
            self.require_role(actor, 'doctor')
            return self.remove(actor, payload)
        if action == 'device':
            return self.device(actor, payload)
        if action == 'acknowledge':
            return self.acknowledge(actor, payload.event_id)
        return self.events(actor, payload.before_id)

    def team(self, actor):
        self.require_role(actor, 'doctor')
        with self.store.connect() as db:
            rows = db.execute("""SELECT id AS account_id,nurse_id AS staff_id,name,email,phone,approval_status,created_at,reviewed_at
                FROM nurses WHERE role='nurse' AND doctor_id=? ORDER BY created_at DESC""", (actor['id'],)).fetchall()
        return {'nurses': [dict(r) for r in rows]}

    def nurse_request(self, actor, account_id):
        self.require_role(actor, 'doctor')
        with self.store.connect() as db:
            nurse = db.execute("SELECT * FROM nurses WHERE id=? AND role='nurse' AND doctor_id=? AND approval_status='pending'",
                               (account_id, actor['id'])).fetchone()
        if nurse is None:
            raise UserError('Pending request not found.', 404)
        return self.accounts.public_profile(nurse, include_card=True)

    def review_nurse(self, actor, data):
        self.require_role(actor, 'doctor')
        with self.engine.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            nurse = db.execute("SELECT * FROM nurses WHERE id=? AND doctor_id=? AND role='nurse' AND approval_status='pending'",
                               (data.account_id, actor['id'])).fetchone()
            if nurse is None:
                raise UserError('This pending request is no longer available.', 404)
            state = 'approved' if data.decision == 'approve' else 'rejected'
            db.execute('UPDATE nurses SET approval_status=?,reviewed_at=? WHERE id=?', (state, time.time(), nurse['id']))
            moved = 0
            if state == 'approved':
                moved = db.execute('UPDATE patients SET doctor_id=? WHERE nurse_id=? AND doctor_id IS NULL',
                                   (actor['id'], nurse['id'])).rowcount
            self.store.audit(db, actor['id'], nurse['id'], 'NURSE_' + state.upper())
        return {'approval_status': state, 'legacy_patients_assigned': moved}

    def owned(self, db, actor, pid):
        patient = db.execute('SELECT * FROM patients WHERE id=? AND doctor_id=? AND removed_at IS NULL',
                             (pid, self.team_id(actor))).fetchone()
        if patient is None:
            raise UserError('Patient not found.', 404)
        return dict(patient)

    def add(self, actor, data):
        self.accounts.confirm(actor, data.password)
        team_id = self.team_id(actor)
        pid = 'P-' + uuid.uuid4().hex[:12].upper()
        with self.engine.lock:
            try:
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute('SELECT count(*) FROM patients WHERE doctor_id=? AND removed_at IS NULL', (team_id,)).fetchone()[0] >= 12:
                        raise UserError('This local demo supports 12 active patients per doctor team.')
                    if db.execute('SELECT count(*) FROM patients WHERE removed_at IS NULL').fetchone()[0] >= 48:
                        raise UserError('This local demo supports 48 active patients in total.')
                    db.execute('INSERT INTO patients(id,nurse_id,name,age,bed,created_at,doctor_id) VALUES(?,?,?,?,?,?,?)',
                               (pid, actor['id'], data.name, data.age, data.bed, time.time(), team_id))
                    self.store.event(db, self.owned(db, actor, pid), 'DEVICE_CONNECTED', actor_id=actor['id'])
            except sqlite3.IntegrityError:
                raise UserError('That bed is already assigned. Choose another bed.', 409) from None
        return {'patient_id': pid}

    def remove(self, actor, data):
        self.require_role(actor, 'doctor')
        self.accounts.confirm(actor, data.password)
        with self.engine.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.owned(db, actor, data.patient_id)
            if p['connected']:
                self.store.event(db, p, 'DEVICE_DISCONNECTED', actor_id=actor['id'])
            db.execute('UPDATE patients SET removed_at=?,connected=0 WHERE id=?', (time.time(), p['id']))
            self.engine.invalidate(p['id'])
        return {}

    def device(self, actor, data):
        with self.engine.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.owned(db, actor, data.patient_id)
            if bool(p['connected']) != data.connected:
                db.execute('UPDATE patients SET connected=? WHERE id=?', (int(data.connected), p['id']))
                self.store.event(db, p, 'DEVICE_CONNECTED' if data.connected else 'DEVICE_DISCONNECTED', actor_id=actor['id'])
                self.engine.invalidate(p['id'])
        return {}

    def acknowledge(self, actor, event_id):
        team = self.team_id(actor)
        with self.store.connect() as db:
            event = db.execute('''SELECT e.* FROM events e JOIN patients p ON p.id=e.patient_id
                WHERE e.id=? AND p.doctor_id=?''', (event_id, team)).fetchone()
            if event is None:
                raise UserError('Event not found.', 404)
            if not needs_ack(event):
                raise UserError('This event does not need acknowledgement.')
            # Keep the identity of the FIRST person who acknowledged it.
            db.execute('UPDATE events SET acknowledged_at=?,acknowledged_by=? WHERE id=? AND acknowledged_at IS NULL',
                       (time.time(), actor['id'], event_id))
        return {}

    def events(self, actor, before_id=None):
        owner = actor['role'] == 'admin'
        team = None if owner else self.team_id(actor)
        with self.store.connect() as db:
            rows = db.execute('''SELECT e.id,e.patient_id,p.name AS patient_name,p.bed,p.removed_at,
              e.kind,e.old_status,e.new_status,e.occurred_at,e.acknowledged_at,
              a.name AS acknowledged_by,a.nurse_id AS acknowledged_by_id,a.role AS acknowledged_by_role,
              d.name AS doctor_name,d.nurse_id AS doctor_staff_id,c.name AS action_by
              FROM events e JOIN patients p ON p.id=e.patient_id
              LEFT JOIN nurses a ON a.id=e.acknowledged_by LEFT JOIN nurses d ON d.id=p.doctor_id
              LEFT JOIN nurses c ON c.id=e.actor_id
              WHERE (?=1 OR p.doctor_id=?) AND (? IS NULL OR e.id<?)
              ORDER BY e.id DESC LIMIT 51''', (int(owner), team, before_id, before_id)).fetchall()
        return {'events': [dict(r) for r in rows[:50]], 'has_more': len(rows) > 50}

    def status(self, p):
        if not p['doctor_id']:
            return 'UNASSIGNED', None, None
        if not p['connected']:
            return 'DISCONNECTED', None, None
        latest = self.engine.latest.get(p['id'])
        if not latest:
            return 'WAITING', None, None
        status = 'STALE' if time.time() - latest['measured_at'] > 15 else latest['status']
        readings = dict(latest['vitals']) if status in {'NORMAL', 'ELEVATED', 'CRITICAL'} else None
        return status, readings, latest['measured_at']

    def dashboard(self, actor):
        team = self.team_id(actor)
        with self.engine.lock, self.store.connect() as db:
            rows = db.execute('SELECT id,name,age,bed,connected,created_at,doctor_id FROM patients WHERE doctor_id=? AND removed_at IS NULL ORDER BY bed',
                              (team,)).fetchall()
            result = []
            for row in rows:
                p = dict(row)
                p['status'], p['vitals'], p['measured_at'] = self.status(p)
                result.append(p)
            pending = db.execute(f'''SELECT count(*) FROM events e JOIN patients p ON p.id=e.patient_id
                WHERE p.doctor_id=? AND e.acknowledged_at IS NULL AND {ACK_SQL}''', (team,)).fetchone()[0]
            requests = db.execute("SELECT count(*) FROM nurses WHERE doctor_id=? AND role='nurse' AND approval_status='pending'", (team,)).fetchone()[0]
        return {'patients': result, 'pending_alerts': pending, 'updated_at': time.time(),
                'pending_requests': requests if actor['role'] == 'doctor' else 0}

    def admin_overview(self):
        with self.engine.lock, self.store.connect() as db:
            staff = db.execute('''SELECT n.name,n.nurse_id AS staff_id,n.role,n.email,n.approval_status,
                d.name AS doctor_name,d.nurse_id AS doctor_staff_id FROM nurses n
                LEFT JOIN nurses d ON d.id=n.doctor_id WHERE n.role<>'admin' ORDER BY n.role,n.name''').fetchall()
            rows = db.execute('''SELECT p.*,d.name AS doctor_name,d.nurse_id AS doctor_staff_id,c.name AS added_by
                FROM patients p LEFT JOIN nurses d ON d.id=p.doctor_id LEFT JOIN nurses c ON c.id=p.nurse_id
                WHERE p.removed_at IS NULL ORDER BY d.name,p.bed''').fetchall()
            patients = []
            for row in rows:
                p = dict(row)
                # Explicit allowlist: no raw vital fields in an owner response.
                item = {k: p[k] for k in ['id', 'name', 'bed', 'doctor_name', 'doctor_staff_id', 'added_by']}
                item['status'] = self.status(p)[0]
                patients.append(item)
        return {'staff': [dict(s) for s in staff], 'patients': patients, 'updated_at': time.time()}

    def admin_audit(self, before_id=None):
        with self.store.connect() as db:
            rows = db.execute('''SELECT t.id,t.action,t.occurred_at,a.name AS decision_by,a.nurse_id AS decision_by_id,
                n.name AS nurse_name,n.nurse_id AS nurse_id FROM staff_audit t
                LEFT JOIN nurses a ON a.id=t.actor_id JOIN nurses n ON n.id=t.subject_id
                WHERE (? IS NULL OR t.id<?) ORDER BY t.id DESC LIMIT 51''', (before_id, before_id)).fetchall()
        return {'audit': [dict(r) for r in rows[:50]], 'has_more': len(rows)>50}
