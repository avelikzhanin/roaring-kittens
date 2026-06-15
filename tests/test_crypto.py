from cryptography.fernet import Fernet

from roaring_kittens.security.crypto import decrypt_secret, encrypt_secret


def test_roundtrip():
    key = Fernet.generate_key().decode()
    token = "t.super-secret-tinkoff-token"
    blob = encrypt_secret(token, key)
    assert blob != token.encode()
    assert decrypt_secret(blob, key) == token
