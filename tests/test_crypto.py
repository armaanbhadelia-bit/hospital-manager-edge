import base64
import time
import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from secure_channel import check_fresh, decrypt, encrypt


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.key = AESGCM.generate_key(bit_length=256)
        self.payload = {'patient_id': 'P-01', 'vitals': {'heart_rate': 72.0}}

    def test_request_and_response_round_trip(self):
        for direction in ['request', 'response']:
            packet = encrypt(self.payload, self.key, direction)
            self.assertEqual(decrypt(packet, self.key, direction), self.payload)
            self.assertNotIn('patient_id', packet)

    def test_same_payload_has_fresh_nonce_and_ciphertext(self):
        a = encrypt(self.payload, self.key, 'request')
        b = encrypt(self.payload, self.key, 'request')
        self.assertNotEqual(a['nonce'], b['nonce'])
        self.assertNotEqual(a['ciphertext'], b['ciphertext'])

    def test_tampering_is_rejected(self):
        packet = encrypt(self.payload, self.key, 'request')
        damaged = bytearray(base64.b64decode(packet['ciphertext']))
        damaged[0] ^= 1
        packet['ciphertext'] = base64.b64encode(damaged).decode()
        with self.assertRaises(InvalidTag):
            decrypt(packet, self.key, 'request')

    def test_wrong_key_is_rejected(self):
        packet = encrypt(self.payload, self.key, 'request')
        with self.assertRaises(InvalidTag):
            decrypt(packet, AESGCM.generate_key(bit_length=256), 'request')

    def test_request_cannot_be_used_as_response(self):
        packet = encrypt(self.payload, self.key, 'request')
        with self.assertRaises(InvalidTag):
            decrypt(packet, self.key, 'response')

    def test_freshness(self):
        check_fresh(time.time())
        for timestamp in [time.time() - 121, time.time() + 20, float('nan'), float('inf'), None, True]:
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                check_fresh(timestamp)

    def test_invalid_nonce(self):
        packet = encrypt(self.payload, self.key, 'request')
        packet['nonce'] = base64.b64encode(b'short').decode()
        with self.assertRaises(ValueError):
            decrypt(packet, self.key, 'request')

    def test_nonfinite_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            encrypt({'heart_rate': float('nan')}, self.key, 'request')
