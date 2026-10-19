import base64
import hashlib
import hmac
import io
import os
import warnings
from PIL import Image, ImageOps


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(digest).decode()


def verify_password(password, stored):
    try:
        algorithm, salt, digest = stored.split('$')
        if algorithm != 'scrypt':
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def clean_image(encoded):
    """Require a real JPEG/PNG; bound pixels, normalize and strip metadata."""
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not 1 <= len(raw) <= 2_000_000:
            raise ValueError()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG'} or source.width * source.height > 16_000_000:
                    raise ValueError()
                source.load()
                normalized = ImageOps.exif_transpose(source).convert('RGB')
                normalized.thumbnail((1600, 1600))
                output = io.BytesIO()
                normalized.save(output, format='JPEG', quality=88)
        return output.getvalue()
    except Exception as exc:
        raise ValueError('Upload a valid PNG/JPEG under 2 MB and 16 megapixels.') from exc
