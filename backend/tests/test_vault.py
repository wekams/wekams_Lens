"""Credential vault tests.

The vault is security-critical: connector passwords go through encrypt() on
write and decrypt() on read. Anything that breaks the round-trip silently is
a data-loss bug. Anything that breaks the algorithm is a leak bug.
"""

from __future__ import annotations

import pytest


def test_round_trip_basic():
    from app.catalog.vault import decrypt, encrypt

    plaintext = "super-secret-password"
    cipher = encrypt(plaintext)
    assert isinstance(cipher, bytes)
    assert plaintext.encode() not in cipher  # not a passthrough
    assert decrypt(cipher) == plaintext


def test_round_trip_unicode():
    from app.catalog.vault import decrypt, encrypt

    plaintext = "p4ss-wørd-密码-🔑"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_round_trip_empty_string():
    from app.catalog.vault import decrypt, encrypt

    assert decrypt(encrypt("")) == ""


def test_ciphertext_includes_randomness():
    """Two encryptions of the same plaintext must differ (Fernet uses random IV)."""
    from app.catalog.vault import encrypt

    a = encrypt("hello")
    b = encrypt("hello")
    assert a != b, "ciphertext is deterministic — IV is missing"


def test_decrypt_rejects_tampered_ciphertext():
    """Flipping a byte must cause decryption to fail rather than yield garbage."""
    from cryptography.fernet import InvalidToken

    from app.catalog.vault import decrypt, encrypt

    cipher = bytearray(encrypt("hello"))
    cipher[-1] ^= 0x01  # flip last byte
    with pytest.raises(InvalidToken):
        decrypt(bytes(cipher))
