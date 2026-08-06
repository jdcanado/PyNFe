"""Schemas de webhooks: configuração, histórico de entregas e teste."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WebhookConfigRequest(BaseModel):
    """Atualização da configuração de webhook da empresa."""

    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_secret: str | None = Field(default=None, max_length=128)


class WebhookConfigResponse(BaseModel):
    """Configuração salva (segredo mascarado na resposta)."""

    webhook_url: str | None = None
    webhook_secret: str | None = None


class WebhookLogResponse(BaseModel):
    """Registro de uma tentativa de entrega de webhook."""

    id: UUID
    nota_id: UUID | None = None
    event: str
    url: str
    status_code: int | None = None
    tentativa: int
    sucesso: bool
    created_at: datetime


class WebhookTestResponse(BaseModel):
    """Resultado do envio de um evento de teste."""

    ok: bool
    event: str
    tentativas: int = 0
