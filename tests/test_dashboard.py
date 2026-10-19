"""Real HTTP and Streamlit checks for the three role-specific screens."""
import io
import os
import base64
import secrets
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import uvicorn
from streamlit.testing.v1 import AppTest
from client import call
from security import hash_password
from server import create_app

PASSWORD = 'Role-test-password-2468!'


class DashboardTest(unittest.TestCase):
    def new_view(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()

    def signup(self, role, staff_id, email, doctor_id=None):
        at = self.new_view()
        next(e for e in at.radio if e.label == 'Account').set_value('Create account').run()
        next(e for e in at.radio if e.label == 'Sign up as').set_value(role).run()
        fields = {'Full name': role + ' Demo', role + ' ID': staff_id, 'Email': email,
                  'Phone number': '+91 9876543210', 'Choose password': PASSWORD, 'Confirm password': PASSWORD}
        if doctor_id:
            fields['Your doctor’s registered ID'] = doctor_id
        for label, value in fields.items():
            next(e for e in at.text_input if e.label == label).set_value(value)
        image = io.BytesIO(); Image.new('RGB', (32, 32), '#0d9488').save(image, format='PNG')
        for uploader in at.get('file_uploader'):
            uploader.set_value(('demo.png', image.getvalue(), 'image/png'))
        next(e for e in at.button if e.label == 'Create account').click().run()
        self.assertFalse(at.exception, [e.message for e in at.exception])
        self.assertEqual(next(e for e in at.radio if e.label == 'Account').value, 'Log in')
        return self.login(at, email)

    def login(self, at, email):
        next(e for e in at.text_input if e.label == 'Email').set_value(email)
        next(e for e in at.text_input if e.label == 'Password').set_value(PASSWORD)
        next(e for e in at.button if e.label == 'Log in').click().run()
        self.assertFalse(at.exception, [e.message for e in at.exception])
        return at

    def test_three_role_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            listener = socket.socket(); listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            values = {'HOSPITAL_MASTER_KEY': base64.b64encode(secrets.token_bytes(32)).decode(),
                      'HOSPITAL_API_TOKEN': secrets.token_urlsafe(32), 'HOSPITAL_DATA_DIR': temp,
                      'HOSPITAL_API_URL': f'http://127.0.0.1:{port}',
                      'HOSPITAL_ADMIN_EMAIL': 'owner@example.test', 'HOSPITAL_ADMIN_PASSWORD_HASH': hash_password(PASSWORD)}
            with patch.dict(os.environ, values):
                backend = create_app()
                server = uvicorn.Server(uvicorn.Config(backend, log_level='error', access_log=False))
                thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 15
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(.1)
                    self.assertTrue(server.started)
                    doctor = self.signup('Doctor', 'D-TEST', 'doctor@example.test')
                    nurse = self.signup('Nurse', 'N-TEST', 'nurse@example.test', 'D-TEST')
                    self.assertTrue(any('Awaiting doctor approval' in e.value for e in nurse.warning))
                    self.assertNotIn('Add patient', [e.label for e in nurse.button])
                    doctor.run()
                    next(e for e in doctor.button if e.label == 'Review credentials').click().run()
                    self.assertFalse(doctor.exception, [e.message for e in doctor.exception])
                    next(e for e in doctor.button if e.label == 'Approve nurse').click().run()
                    self.assertFalse(doctor.exception, [e.message for e in doctor.exception])
                    nurse.run()
                    self.assertFalse(nurse.exception, [e.message for e in nurse.exception])
                    self.assertNotIn('Remove patient', [e.label for e in nurse.button])
                    for label, value in {'Patient name / label': 'Team patient', 'Bed / room': 'TEAM-01',
                                         'Your password to add this patient': PASSWORD}.items():
                        next(e for e in nurse.text_input if e.label == label).set_value(value)
                    next(e for e in nurse.button if e.label == 'Add patient').click().run()
                    self.assertFalse(nurse.exception, [e.message for e in nurse.exception])
                    session = nurse.session_state['session']
                    pid = call('dashboard', session=session)['patients'][0]['id']
                    deadline = time.monotonic() + 12
                    snapshot = None
                    while time.monotonic() < deadline:
                        snapshot = call('dashboard', session=session)['patients'][0]
                        if snapshot['vitals']:
                            break
                        time.sleep(.2)
                    self.assertIsNotNone(snapshot['vitals'])
                    doctor.run()
                    self.assertEqual(call('dashboard', session=doctor.session_state['session'])['patients'][0]['id'], pid)
                    # Force a category event to exercise acknowledgement controls deterministically.
                    with backend.state.engine.lock:
                        backend.state.store.record_status(pid, 'CRITICAL')
                    nurse.run()
                    next(e for e in nurse.button if e.label == 'Acknowledge alert').click().run()
                    self.assertFalse(nurse.exception, [e.message for e in nurse.exception])
                    rows = call('events', session=session)['events']
                    self.assertTrue(any(e['acknowledged_by_id'] == 'N-TEST' for e in rows))
                    owner = self.login(self.new_view(), 'owner@example.test')
                    self.assertIn('Hospital overview', [e.value for e in owner.title])
                    for label in ['Add patient', 'Remove patient', 'Acknowledge alert', 'Approve nurse', 'Disconnect sensor']:
                        self.assertNotIn(label, [e.label for e in owner.button])
                    self.assertFalse(owner.exception, [e.message for e in owner.exception])
                    next(e for e in doctor.text_input if e.label == 'Your password to remove this patient').set_value(PASSWORD)
                    doctor.checkbox[0].check()
                    next(e for e in doctor.button if e.label == 'Remove patient').click().run()
                    self.assertFalse(doctor.exception, [e.message for e in doctor.exception])
                    self.assertEqual(call('dashboard', session=session)['patients'], [])
                    background = call('add_patient', {'name': 'Background', 'age': 35, 'bed': 'BG', 'password': PASSWORD}, session)['patient_id']
                    for view in [doctor, nurse, owner]:
                        next(e for e in view.button if e.label == 'Log out').click().run()
                        self.assertFalse(view.exception)
                    deadline = time.monotonic() + 12
                    while background not in backend.state.engine.latest and time.monotonic() < deadline:
                        time.sleep(.2)
                    self.assertIn(background, backend.state.engine.latest)
                finally:
                    server.should_exit = True; thread.join(timeout=30); listener.close()
                    self.assertFalse(thread.is_alive())
