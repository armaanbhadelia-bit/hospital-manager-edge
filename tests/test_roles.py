import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from secure_channel import seal_image
from security import hash_password, token_hash
from server import create_app
from storage import SCHEMA
import unittest
import test_system
from test_system import PASSWORD, image_string


class RoleTests(unittest.TestCase):
    setUp = test_system.SystemTests.setUp
    tearDown = test_system.SystemTests.tearDown
    command = test_system.SystemTests.command
    signup = test_system.SystemTests.signup
    doctor = test_system.SystemTests.doctor
    add = test_system.SystemTests.add
    def register_nurse(self, tag, doctor='N-doc'):
        result = self.signup(tag, role='nurse', doctor_id=doctor)
        self.assertTrue(result['ok'], result)
        login = self.command('login', {'email': tag + '@example.test', 'password': PASSWORD})
        return login['data']['session'], login['data']['profile']['account_id']

    def approve(self, doctor_session, nurse_id):
        result = self.command('review_nurse', {'account_id': nurse_id, 'decision': 'approve'}, doctor_session)
        self.assertTrue(result['ok'], result)

    def test_pending_nurse_has_no_patient_access(self):
        doctor = self.doctor('doc'); self.add(doctor)
        nurse, uid = self.register_nurse('pending')
        for action, data in [('dashboard', {}), ('events', {}),
                             ('add_patient', {'name': 'P', 'age': 30, 'bed': 'B', 'password': PASSWORD}),
                             ('admin_overview', {}), ('team', {})]:
            self.assertEqual(self.command(action, data, nurse)['code'], 403)
        self.assertEqual(self.command('account_state', session=nurse)['data']['approval_status'], 'pending')
        self.assertEqual(self.signup('bad', role='nurse', doctor_id='MISSING')['code'], 400)
        self.assertEqual(self.signup('root', role='admin')['code'], 422)

    def test_only_requested_doctor_can_review_credentials_and_approve(self):
        doctor, other = self.doctor('doc'), self.doctor('other')
        nurse, uid = self.register_nurse('review')
        profile = self.command('nurse_request', {'account_id': uid}, doctor)['data']
        self.assertIn('id_card', profile)
        self.assertNotIn('password', profile)
        self.assertNotIn('password_hash', profile)
        self.assertEqual(self.command('nurse_request', {'account_id': uid}, other)['code'], 404)
        self.assertEqual(self.command('review_nurse', {'account_id': uid, 'decision': 'approve'}, other)['code'], 404)
        self.assertEqual(self.command('review_nurse', {'account_id': uid, 'decision': 'approve'}, nurse)['code'], 403)
        self.approve(doctor, uid)
        self.assertEqual(self.command('account_state', session=nurse)['data']['approval_status'], 'approved')
        self.assertEqual(self.command('review_nurse', {'account_id': uid, 'decision': 'reject'}, doctor)['code'], 404)

    def test_team_sharing_and_doctor_only_removal(self):
        doctor, other = self.doctor('doc'), self.doctor('other')
        first, uid1 = self.register_nurse('first'); second, uid2 = self.register_nurse('second')
        self.approve(doctor, uid1); self.approve(doctor, uid2)
        pid = self.add(first)
        for token in [doctor, first, second]:
            self.assertEqual(self.command('dashboard', session=token)['data']['patients'][0]['id'], pid)
        self.assertEqual(self.command('dashboard', session=other)['data']['patients'], [])
        self.assertEqual(self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, first)['code'], 403)
        self.assertEqual(self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, other)['code'], 404)
        self.assertEqual(self.command('remove_patient', {'patient_id': pid, 'password': 'bad'}, doctor)['code'], 403)
        self.assertTrue(self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, doctor)['ok'])

    def test_acknowledgement_records_first_team_member(self):
        doctor = self.doctor('doc')
        nurse, uid = self.register_nurse('acker'); self.approve(doctor, uid)
        pid = self.add(nurse); self.app.state.store.record_status(pid, 'CRITICAL')
        event = self.command('events', session=doctor)['data']['events'][0]
        self.assertTrue(self.command('acknowledge', {'event_id': event['id']}, nurse)['ok'])
        self.assertTrue(self.command('acknowledge', {'event_id': event['id']}, doctor)['ok'])
        row = self.command('events', session=doctor)['data']['events'][0]
        self.assertEqual(row['acknowledged_by_id'], 'N-ACKER')
        self.assertEqual(row['acknowledged_by_role'], 'nurse')
        self.assertIsNotNone(row['acknowledged_at'])

    def test_rejection_reapplication_and_approval_audit(self):
        doctor, other = self.doctor('doc'), self.doctor('other')
        nurse, uid = self.register_nurse('retry')
        self.command('review_nurse', {'account_id': uid, 'decision': 'reject'}, doctor)
        self.assertEqual(self.command('account_state', session=nurse)['data']['approval_status'], 'rejected')
        self.assertEqual(self.command('dashboard', session=nurse)['code'], 403)
        self.assertTrue(self.command('request_team', {'doctor_id': 'N-other'}, nurse)['ok'])
        self.approve(other, uid)
        self.assertEqual(self.command('request_team', {'doctor_id': 'N-doc'}, nurse)['code'], 409)
        with self.app.state.store.connect() as db:
            actions = [r[0] for r in db.execute('SELECT action FROM staff_audit WHERE subject_id=? ORDER BY id', (uid,))]
        self.assertEqual(actions, ['TEAM_REQUESTED', 'NURSE_REJECTED', 'TEAM_REQUESTED', 'NURSE_APPROVED'])

    def test_admin_is_status_only_and_all_mutations_blocked(self):
        doctor = self.doctor('doc'); nurse, uid = self.register_nurse('team'); self.approve(doctor, uid)
        pid = self.add(nurse)
        self.app.state.engine.sender = lambda *args: {'status': 'CRITICAL'}
        self.app.state.engine.tick()
        with patch.dict(os.environ, {'HOSPITAL_ADMIN_EMAIL': 'owner@example.test', 'HOSPITAL_ADMIN_PASSWORD_HASH': hash_password(PASSWORD)}):
            self.app.state.service.accounts.configure_admin()
        owner = self.command('login', {'email': 'owner@example.test', 'password': PASSWORD})['data']['session']
        view = self.command('admin_overview', session=owner)['data']
        self.assertEqual(view['patients'][0]['status'], 'CRITICAL')
        for key in ['vitals', 'heart_rate', 'oxygen_saturation', 'respiratory_rate', 'mse_loss', 'password_hash']:
            self.assertNotIn(key, json.dumps(view))
        events = self.command('admin_events', session=owner)['data']['events']
        self.assertTrue(self.command('admin_audit', session=owner)['data']['audit'])
        changes = [('dashboard', {}), ('add_patient', {'name': 'P', 'age': 30, 'bed': 'B', 'password': PASSWORD}),
                   ('remove_patient', {'patient_id': pid, 'password': PASSWORD}),
                   ('device', {'patient_id': pid, 'connected': False}),
                   ('acknowledge', {'event_id': events[0]['id']}),
                   ('review_nurse', {'account_id': uid, 'decision': 'approve'}),
                   ('request_team', {'doctor_id': 'N-doc'})]
        for action, data in changes:
            with self.subTest(action=action):
                self.assertEqual(self.command(action, data, owner)['code'], 403)
        self.assertEqual(self.command('admin_overview', session=nurse)['code'], 403)

    def test_legacy_migration_keeps_accounts_images_patients_and_events(self):
        self.client.__exit__(None, None, None)
        folder = Path(self.temp.name) / 'legacy'; folder.mkdir()
        database = folder / 'hospital.sqlite3'
        import base64
        photo = base64.b64decode(image_string())
        with sqlite3.connect(database) as db:
            db.executescript(SCHEMA)
            db.execute('INSERT INTO nurses VALUES(?,?,?,?,?,?,?,?,?)',
                       ('legacy-user', 'N-OLD', 'Old Nurse', 'old@example.test', '1234567890', hash_password(PASSWORD),
                        seal_image(photo, self.key, 'legacy-user', 'photo'), seal_image(photo, self.key, 'legacy-user', 'id_card'), time.time()))
            db.execute('INSERT INTO patients(id,nurse_id,name,age,bed,created_at,last_status) VALUES(?,?,?,?,?,?,?)',
                       ('P-OLD', 'legacy-user', 'Old Patient', 35, 'OLD-01', time.time(), 'CRITICAL'))
            db.execute('INSERT INTO events(nurse_id,patient_id,kind,new_status,occurred_at,acknowledged_at) VALUES(?,?,?,?,?,?)',
                       ('legacy-user', 'P-OLD', 'CRITICAL', 'CRITICAL', time.time(), time.time()))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash('old-token'), 'legacy-user', time.time() + 1000))
        os.environ['HOSPITAL_DATA_DIR'] = str(folder)
        self.app = create_app(start_simulator=False); self.client = TestClient(self.app); self.client.__enter__()
        backups = list(folder.glob('hospital.before_roles_*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as db:
            self.assertNotIn('role', [r[1] for r in db.execute('PRAGMA table_info(nurses)')])
            self.assertEqual(db.execute('SELECT count(*) FROM patients').fetchone()[0], 1)
        self.assertEqual(self.command('dashboard', session='old-token')['code'], 401)
        login = self.command('login', {'email': 'old@example.test', 'password': PASSWORD})['data']
        legacy = login['session']
        self.assertEqual(login['profile']['approval_status'], 'unassigned')
        self.assertEqual(base64.b64decode(login['profile']['photo']), photo)
        self.assertEqual(self.command('dashboard', session=legacy)['code'], 403)
        doctor = self.doctor('doc')
        self.command('request_team', {'doctor_id': 'N-doc'}, legacy)
        self.approve(doctor, 'legacy-user')
        self.assertEqual(self.command('dashboard', session=doctor)['data']['patients'][0]['id'], 'P-OLD')
        event = self.command('events', session=legacy)['data']['events'][0]
        self.assertIsNotNone(event['acknowledged_at'])
        self.assertIsNone(event['acknowledged_by'])
        self.client.__exit__(None, None, None)
        self.app = create_app(start_simulator=False); self.client = TestClient(self.app); self.client.__enter__()
        self.assertEqual(len(list(folder.glob('hospital.before_roles_*.sqlite3'))), 1)
        self.assertEqual(len(self.command('dashboard', session=doctor)['data']['patients']), 1)
