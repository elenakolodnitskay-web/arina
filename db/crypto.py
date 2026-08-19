from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from config import settings


def _cipher() -> Fernet:
    return Fernet(settings.fernet_key.encode())


def encrypt_text(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_text(token: str) -> str:
    return _cipher().decrypt(token.encode()).decode()


class EncryptedString(TypeDecorator):
    """Строковая колонка, прозрачно шифруемая Fernet при записи и расшифровываемая при чтении."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return encrypt_text(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return decrypt_text(value)
