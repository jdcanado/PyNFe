"""Schemas de autenticação (Pydantic v2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    """Credenciais de API client (enviadas via headers)."""

    api_key: str = Field(description="Chave pública do API client")
    api_secret: str = Field(description="Segredo do API client")


class TokenResponse(BaseModel):
    """Resposta com token JWT."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    api_key_prefix: str
