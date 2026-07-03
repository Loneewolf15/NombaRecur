from cryptography.fernet import Fernet
from app.config import settings

# This key MUST be kept secret and consistent across restarts
f = Fernet(settings.fernet_key.encode())


def encrypt_val(text: str) -> str:
    if not text:
        return text
    return f.encrypt(text.encode()).decode()


def decrypt_val(token: str) -> str:
    if not token:
        return token
    return f.decrypt(token.encode()).decode()
