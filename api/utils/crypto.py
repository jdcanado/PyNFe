"""Criptografia Fernet para senhas de certificado."""

from __future__ import annotations

from cryptography.fernet import Fernet

from api.core.config import get_settings

settings = get_settings()

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.fernet_key.encode())
    return _fernet


def encrypt_senha(senha: str) -> str:
    """Criptografa uma senha com Fernet. Retorna string base64."""
    return _get_fernet().encrypt(senha.encode()).decode()


def decrypt_senha(token: str) -> str:
    """Descriptografa uma senha Fernet. Levanta InvalidToken se inválida."""
    return _get_fernet().decrypt(token.encode()).decode()


def encrypt_bytes(dados: bytes) -> str:
    """Criptografa bytes (ex.: PFX) com Fernet. Retorna string base64."""
    return _get_fernet().encrypt(dados).decode()


def decrypt_bytes(token: str) -> bytes:
    """Descriptografa dados Fernet (base64) de volta para bytes."""
    return _get_fernet().decrypt(token.encode())
