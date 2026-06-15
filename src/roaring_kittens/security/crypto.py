from cryptography.fernet import Fernet


def encrypt_secret(plaintext: str, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(plaintext.encode())


def decrypt_secret(blob: bytes, key: str) -> str:
    return Fernet(key.encode()).decrypt(blob).decode()
