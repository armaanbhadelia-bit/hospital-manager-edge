"""Integration tests use the actual uploaded checkpoint once dependencies exist."""
import base64
import importlib.util
import os
import secrets
import time
import unittest
import uuid

DEPENDENCIES_READY = all(importlib.util.find_spec(m) for m in ['fastapi', 'torch', 'httpx', 'dotenv'])


@unittest.skipUnless(DEPENDENCIES_READY, 'Install requirements.txt for API integration tests')
class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_environment = {k: os.environ.get(k) for k in ['HOSPITAL_MASTER_KEY', 'HOSPITAL_API_TOKEN']}
        cls.key = secrets.token_bytes(32)
        cls.token = secrets.token_urlsafe(32)
        os.environ['HOSPITAL_MASTER_KEY'] = base64.b64encode(cls.key).decode()
        os.environ['HOSPITAL_API_TOKEN'] = cls.token
        from fastapi.testclient import TestClient
        from server import app
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        for key, value in cls.old_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def payload(self):
        return {'request_id': str(uuid.uuid4()), 'patient_id': 'P-TEST', 'node_id': 'test-centre',
                'sent_at': time.time(), 'measured_at': time.time(),
                'vitals': {'heart_rate': 72, 'oxygen_saturation': 98, 'respiratory_rate': 15, 'age': 30}}

    def post(self, payload):
        from secure_channel import encrypt
        return self.client.post('/predict/encrypted', json=encrypt(payload, self.key, 'request'),
                                headers={'Authorization': 'Bearer ' + self.token})

    def test_real_model_encrypted_round_trip(self):
        from secure_channel import decrypt
        payload = self.payload()
        response = self.post(payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('status', response.json())
        result = decrypt(response.json(), self.key, 'response')
        self.assertEqual(result['request_id'], payload['request_id'])
        self.assertEqual(result['patient_id'], payload['patient_id'])
        self.assertIn(result['status'], ['NORMAL', 'ELEVATED', 'CRITICAL'])
        self.assertGreaterEqual(result['mse_loss'], 0)

    def test_replay_is_rejected(self):
        payload = self.payload()
        self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(self.post(payload).status_code, 409)

    def test_expired_reading_is_rejected(self):
        payload = self.payload()
        payload['measured_at'] -= 130
        self.assertEqual(self.post(payload).status_code, 400)

    def test_invalid_vitals_are_rejected(self):
        payload = self.payload()
        payload['vitals']['oxygen_saturation'] = 101
        self.assertEqual(self.post(payload).status_code, 400)

    def test_token_required(self):
        from secure_channel import encrypt
        response = self.client.post('/predict/encrypted', json=encrypt(self.payload(), self.key, 'request'))
        self.assertEqual(response.status_code, 401)

    def test_no_plaintext_prediction_route(self):
        self.assertEqual(self.client.post('/predict', json=self.payload()['vitals']).status_code, 404)
