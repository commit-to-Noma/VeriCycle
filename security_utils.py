import base64
import hashlib
import os


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise RuntimeError("cryptography package is required for key encryption") from exc

    secret = os.getenv("VERICYCLE_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("VERICYCLE_SECRET_KEY is required for key encryption")

    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(value: str) -> str:
    if not value:
        return ""
    token = _fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(value: str) -> str:
    if not value:
        return ""
    plaintext = _fernet().decrypt(value.encode("utf-8"))
    return plaintext.decode("utf-8")
