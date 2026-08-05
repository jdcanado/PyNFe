"""Segurança: verificação de API keys e JWT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from api.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_api_key(plain_api_key: str, api_key_hash: str) -> bool:
    """Verifica uma API key em texto plano contra o hash armazenado."""
    return pwd_context.verify(plain_api_key, api_key_hash)


def hash_api_key(api_key: str) -> str:
    """Gera o hash bcrypt de uma API key."""
    return pwd_context.hash(api_key)


def create_jwt_token(subject: str, extra_claims: dict | None = None) -> str:
    """Cria um token JWT assinado com as configurações da API."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt_token(token: str) -> dict:
    """Decodifica e valida um token JWT. Levanta JWTError em caso de falha."""
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
