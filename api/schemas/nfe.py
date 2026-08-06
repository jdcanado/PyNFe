"""Schemas de NF-e: resposta da emissão."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NFeEmitirResponse(BaseModel):
    """Resposta da emissão de NF-e."""

    id: UUID | None = None
    empresa_id: UUID
    chave_acesso: str = Field(min_length=44, max_length=44)
    numero: int
    serie: int
    modelo: str = "55"
    status: str
    protocolo: str | None = None
    valor_total: float | None = None
    emitida_em: datetime | None = None
    autorizada_em: datetime | None = None
    xml_assinado: str | None = None
    xml_protocolado: str | None = None
    mensagem: str | None = None
