"""Local credential vault.

Encrypts source credentials at rest with a key derived from a passphrase
the admin sets at install time. Implementations can be swapped behind this
interface (e.g. HashiCorp Vault, cloud KMS, HSM) without changing callers.

For dev convenience the key is currently derived from the catalog DB URL
itself; this is **not secure for production** and is intended to be
replaced with an admin-supplied passphrase + KDF.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _derive_key() -> bytes:
    """Derive a Fernet key from a stable secret.

    TODO(Phase 1c): replace with an admin-supplied passphrase + Argon2id KDF
    and refuse to start if no passphrase is configured.
    """
    seed = settings.catalog_db_url.encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    return _fernet.decrypt(ciphertext).decode("utf-8")
