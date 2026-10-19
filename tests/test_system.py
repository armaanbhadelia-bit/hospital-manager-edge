import base64
import io
import os
import secrets
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from security import hash_password, verify_password
from secure_channel import check_fresh, decrypt, encrypt
from server import create_app
from simulator import FakePatient

PASSWORD = 'Testing-nurse-2468!'


def image_string():
    output = io.BytesIO()
    Image.new('RGB', (32, 32), '#0d9488').save(output, format='PNG')
    return base64.b64encode(output.getvalue()).decode()


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = secrets.token_bytes(32)
        self.api_token = secrets.token_urlsafe(32)
        self.env = patch.dict(os.environ, {'HOSPITAL_MASTER_KEY': base64.b64encode(self.key).decode(),
                                         'HOSPITAL_API_TOKEN': self.api_token, 'HOSPITAL_DATA_DIR': self.temp.name,
                                         'HOSPITAL_ADMIN_EMAIL': '', 'HOSPITAL_ADMIN_PASSWORD_HASH': ''})
        self.env.start()
        self.app = create_app(start_simulator=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.temp.cleanup()

    def command(self, action, data=None, session=None):
        payload = {'request_id': str(uuid.uuid4()), 'sent_at': time.time(), 'action': action,
                   'session': session, 'data': data or {}}
        packet = encrypt(payload, self.key, 'centre_request')
        response = self.client.post('/centre/encrypted', json=packet, headers={'Authorization': 'Bearer ' + self.api_token})
        self.assertEqual(response.status_code, 200, response.text)
        result = decrypt(response.json(), self.key, 'centre_response')
        self.assertEqual(result['request_id'], payload['request_id'])
        return result

    def signup(self, tag='one', **overrides):
        data = dict(role='doctor', name='Staff ' + tag, staff_id='N-' + tag, email=tag + '@example.test', phone='+91 9876543210',
                    password=PASSWORD, photo=image_string(), id_card=image_string())
        data.update(overrides)
        return self.command('signup', data)

    def doctor(self, tag='one'):
        result = self.signup(tag)
        self.assertTrue(result['ok'], result)
        result = self.command('login', {'email': tag + '@example.test', 'password': PASSWORD})
        self.assertTrue(result['ok'], result)
        return result['data']['session']

    def add(self, session, bed='A-01'):
        result = self.command('add_patient', {'name': 'Demo patient', 'age': 35, 'bed': bed, 'password': PASSWORD}, session)
        self.assertTrue(result['ok'], result)
        return result['data']['patient_id']

    def predict(self, patient='P-TEST', request_id=None, measured_at=None):
        payload = {'request_id': request_id or str(uuid.uuid4()), 'patient_id': patient,
                   'sent_at': time.time(), 'measured_at': time.time() if measured_at is None else measured_at,
                   'vitals': {'heart_rate': 72, 'oxygen_saturation': 98, 'respiratory_rate': 15, 'age': 30}}
        response = self.client.post('/predict/encrypted', json=encrypt(payload, self.key, 'request'),
                                    headers={'Authorization': 'Bearer ' + self.api_token})
        return response, payload

    def test_signup_profile_and_password_storage(self):
        session = self.doctor()
        profile = self.command('profile', session=session)['data']
        self.assertEqual(profile['email'], 'one@example.test')
        self.assertTrue(base64.b64decode(profile['id_card']).startswith(b'\xff\xd8'))
        with self.app.state.store.connect() as db:
            row = db.execute('SELECT * FROM nurses').fetchone()
            self.assertNotEqual(row['password_hash'], PASSWORD)
            self.assertTrue(verify_password(PASSWORD, row['password_hash']))
            self.assertFalse(row['photo'].startswith(b'\xff\xd8'))
            self.assertNotIn(PASSWORD, '\n'.join(db.iterdump()))

    def test_duplicate_identity_and_case_insensitive_email(self):
        self.doctor()
        self.assertEqual(self.signup('two', email='ONE@EXAMPLE.TEST')['code'], 409)
        self.assertTrue(self.command('login', {'email': 'ONE@EXAMPLE.TEST', 'password': PASSWORD})['ok'])

    def test_images_and_signup_fields_are_required(self):
        self.assertEqual(self.signup(photo='bad image')['code'], 400)
        self.assertEqual(self.signup(password='short')['code'], 422)
        self.assertEqual(self.signup(phone='not a number')['code'], 422)
        self.assertEqual(self.signup(email='invalid')['code'], 422)

    def test_wrong_password_and_lockout(self):
        self.signup()
        for _ in range(5):
            self.assertEqual(self.command('login', {'email': 'one@example.test', 'password': 'wrong'})['code'], 401)
        self.assertEqual(self.command('login', {'email': 'one@example.test', 'password': PASSWORD})['code'], 429)

    def test_login_required_and_logout_revokes(self):
        self.assertEqual(self.command('dashboard')['code'], 401)
        session = self.doctor()
        self.command('logout', session=session)
        self.assertEqual(self.command('dashboard', session=session)['code'], 401)

    def test_password_required_for_add_and_remove(self):
        session = self.doctor()
        bad = self.command('add_patient', {'name': 'P', 'age': 35, 'bed': 'A', 'password': 'wrong'}, session)
        self.assertEqual(bad['code'], 403)
        pid = self.add(session)
        self.assertEqual(self.command('remove_patient', {'patient_id': pid, 'password': 'wrong'}, session)['code'], 403)
        self.assertEqual(len(self.command('dashboard', session=session)['data']['patients']), 1)

    def test_cross_team_access_is_blocked(self):
        one, two = self.doctor('one'), self.doctor('two')
        pid = self.add(one)
        self.assertEqual(self.command('dashboard', session=two)['data']['patients'], [])
        self.assertEqual(self.command('events', session=two)['data']['events'], [])
        self.assertEqual(self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, two)['code'], 404)
        self.assertEqual(self.command('device', {'patient_id': pid, 'connected': False}, two)['code'], 404)
        self.app.state.store.record_status(pid, 'CRITICAL')
        event = self.command('events', session=one)['data']['events'][0]
        self.assertEqual(self.command('acknowledge', {'event_id': event['id']}, two)['code'], 404)
        forged = self.command('add_patient', {'name': 'P', 'age': 35, 'bed': 'B', 'password': PASSWORD, 'nurse_id': 'forged'}, two)
        self.assertEqual(forged['code'], 422)

    def test_status_changes_only_no_initial_normal_log(self):
        session = self.doctor(); pid = self.add(session)
        for status in ['NORMAL', 'NORMAL', 'ELEVATED', 'ELEVATED', 'CRITICAL', 'CRITICAL', 'ELEVATED', 'ELEVATED', 'NORMAL', 'NORMAL']:
            self.app.state.store.record_status(pid, status)
        events = self.command('events', session=session)['data']['events']
        self.assertEqual([e['kind'] for e in reversed(events)], ['DEVICE_CONNECTED', 'ELEVATED', 'CRITICAL', 'ELEVATED', 'RETURNED_NORMAL'])
        self.assertEqual(self.command('dashboard', session=session)['data']['pending_alerts'], 2)
        improvement = next(e for e in events if e['kind'] == 'ELEVATED' and e['old_status'] == 'CRITICAL')
        self.assertEqual(self.command('acknowledge', {'event_id': improvement['id']}, session)['code'], 400)

    def test_disconnect_reconnect_and_remove(self):
        session = self.doctor(); pid = self.add(session)
        for connected in [False, False, True, True]:
            self.assertTrue(self.command('device', {'patient_id': pid, 'connected': connected}, session)['ok'])
        self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, session)
        self.assertEqual(self.command('dashboard', session=session)['data']['patients'], [])
        events = self.command('events', session=session)['data']['events']
        self.assertEqual(len(events), 4)
        self.assertTrue(all(e['removed_at'] for e in events))

    def test_acknowledgement_does_not_change_status(self):
        session = self.doctor(); pid = self.add(session)
        self.app.state.store.record_status(pid, 'CRITICAL')
        event = self.command('events', session=session)['data']['events'][0]
        self.assertTrue(self.command('acknowledge', {'event_id': event['id']}, session)['ok'])
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT last_status FROM patients WHERE id=?', (pid,)).fetchone()[0], 'CRITICAL')

    def test_model_encrypted_round_trip(self):
        response, payload = self.predict()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('status', response.json())
        result = decrypt(response.json(), self.key, 'response')
        self.assertEqual(result['request_id'], payload['request_id'])
        self.assertEqual(result['status'], 'NORMAL')
        self.assertGreaterEqual(result['mse_loss'], 0)

    def test_replayed_and_expired_readings_rejected(self):
        rid = str(uuid.uuid4())
        self.assertEqual(self.predict(request_id=rid)[0].status_code, 200)
        self.assertEqual(self.predict(request_id=rid)[0].status_code, 409)
        self.assertEqual(self.predict(measured_at=time.time() - 130)[0].status_code, 400)

    def test_api_token_required_and_no_plaintext_route(self):
        response, payload = self.predict()
        packet = encrypt(payload, self.key, 'request')
        self.assertEqual(self.client.post('/predict/encrypted', json=packet).status_code, 401)
        self.assertEqual(self.client.post('/predict', json=payload).status_code, 404)

    def test_latest_only_no_raw_readings_on_disk(self):
        session = self.doctor(); pid = self.add(session)
        engine = self.app.state.engine
        engine.sender = lambda *args: {'status': 'NORMAL'}
        for _ in range(5):
            engine.tick()
        self.assertEqual(len(engine.latest), 1)
        self.assertEqual(len(self.command('events', session=session)['data']['events']), 1)
        self.assertIsNotNone(self.command('dashboard', session=session)['data']['patients'][0]['vitals'])
        with self.app.state.store.connect() as db:
            dump = '\n'.join(db.iterdump())
        for forbidden in ['heart_rate', 'oxygen_saturation', 'respiratory_rate', 'mse_loss']:
            self.assertNotIn(forbidden, dump)

    def test_offline_and_restore_are_not_unplug_events(self):
        session = self.doctor(); self.add(session)
        engine = self.app.state.engine
        def fail(*args):
            raise ConnectionError()
        engine.sender = fail
        engine.tick(); engine.tick()
        dashboard = self.command('dashboard', session=session)['data']['patients'][0]
        self.assertEqual(dashboard['status'], 'OFFLINE')
        self.assertIsNone(dashboard['vitals'])
        engine.sender = lambda *args: {'status': 'NORMAL'}
        engine.tick()
        events = self.command('events', session=session)['data']['events']
        self.assertEqual([e['kind'] for e in reversed(events)], ['DEVICE_CONNECTED', 'INFERENCE_UNAVAILABLE', 'INFERENCE_RESTORED'])

    def test_stale_values_are_hidden(self):
        session = self.doctor(); pid = self.add(session)
        engine = self.app.state.engine
        engine.sender = lambda *args: {'status': 'NORMAL'}
        engine.tick()
        engine.latest[pid]['measured_at'] -= 20
        row = self.command('dashboard', session=session)['data']['patients'][0]
        self.assertEqual(row['status'], 'STALE')
        self.assertIsNone(row['vitals'])

    def test_patient_removed_during_inference_stays_removed(self):
        session = self.doctor(); pid = self.add(session)
        def remove_during_request(*args):
            reply = self.command('remove_patient', {'patient_id': pid, 'password': PASSWORD}, session)
            self.assertTrue(reply['ok'])
            return {'status': 'CRITICAL'}
        self.app.state.engine.sender = remove_during_request
        self.app.state.engine.tick()
        self.assertNotIn(pid, self.app.state.engine.latest)
        self.assertFalse(any(e['kind'] == 'CRITICAL' for e in self.command('events', session=session)['data']['events']))

    def test_restart_preserves_accounts_assignments_and_events_not_readings(self):
        session = self.doctor(); pid = self.add(session)
        self.app.state.store.record_status(pid, 'ELEVATED')
        self.app.state.engine.sender = lambda *args: {'status': 'ELEVATED'}
        self.app.state.engine.tick()
        self.client.__exit__(None, None, None)
        self.app = create_app(start_simulator=False)
        self.client = TestClient(self.app); self.client.__enter__()
        dashboard = self.command('dashboard', session=session)['data']['patients']
        self.assertEqual(dashboard[0]['id'], pid)
        self.assertEqual(dashboard[0]['status'], 'WAITING')
        self.assertIsNone(dashboard[0]['vitals'])
        self.assertEqual(len(self.command('events', session=session)['data']['events']), 2)


class CryptoAndSimulationTests(unittest.TestCase):
    def test_tampering_wrong_key_and_direction(self):
        key = secrets.token_bytes(32)
        packet = encrypt({'example': 1}, key, 'request')
        for wrong_key, domain in [(secrets.token_bytes(32), 'request'), (key, 'response'), (key, 'centre_request')]:
            with self.assertRaises(InvalidTag):
                decrypt(packet, wrong_key, domain)
        damaged = bytearray(base64.b64decode(packet['ciphertext'])); damaged[0] ^= 1
        packet['ciphertext'] = base64.b64encode(damaged).decode()
        with self.assertRaises(InvalidTag):
            decrypt(packet, key, 'request')

    def test_nonce_randomness_freshness_and_nonfinite(self):
        key = secrets.token_bytes(32)
        self.assertNotEqual(encrypt({}, key, 'request')['nonce'], encrypt({}, key, 'request')['nonce'])
        for value in [None, True, float('nan'), float('inf'), time.time() - 130]:
            with self.assertRaises(ValueError):
                check_fresh(value)
        with self.assertRaises(ValueError):
            encrypt({'hr': float('nan')}, key, 'request')

    def test_salted_password_hash(self):
        first, second = hash_password(PASSWORD), hash_password(PASSWORD)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(PASSWORD, first))
        self.assertFalse(verify_password('wrong', first))

    def test_fake_patient_is_smooth_and_variable(self):
        patient = {'id': 'P-DEMO', 'created_at': 0, 'age': 35}
        fake = FakePatient(patient)
        readings = [fake.reading(patient, t) for t in range(0, 600, 3)]
        self.assertGreater(max(v['heart_rate'] for v in readings) - min(v['heart_rate'] for v in readings), 30)
        for a, b in zip(readings, readings[1:]):
            self.assertLess(abs(a['heart_rate'] - b['heart_rate']), 15)
            self.assertTrue(78 <= b['oxygen_saturation'] <= 100)
            self.assertEqual(b['age'], 35)


if __name__ == '__main__':
    unittest.main()
