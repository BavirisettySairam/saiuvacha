import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import models


def _get_fernet():
    keys = getattr(settings, 'FERNET_KEYS', None)
    if keys:
        return MultiFernet([Fernet(k) for k in keys])
    # Derive a valid Fernet key from SECRET_KEY (dev fallback)
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


class EncryptedTextField(models.TextField):
    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except Exception:
            return value  # safety: return raw if decryption fails

    def get_prep_value(self, value):
        if value is None:
            return value
        return _get_fernet().encrypt(value.encode()).decode()
