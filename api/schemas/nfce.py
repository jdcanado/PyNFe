"""Schemas de NFC-e (modelo 65): emissão e resposta."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import validar_chave_acesso, validar_cnpj


class NFCeEmitirRequest(BaseModel):
    """Requisição de emissão de NFC-e (consumo, modelo 65)."""

    empresa_id: UUID
    cnpj: str = Field(description="CNPJ do emitente (14 dígitos)")
    numero: int = Field(ge=1, le=999_999_999)
    serie: int = Field(default=1, ge=0, le=999)
    valor_total: float = Field(gt=0)
    chave_acesso: str | None = Field(
        default=None, description="Chave de acesso (44 dígitos); gerada pela API se ausente"
    )

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str) -> str:
        return validar_cnpj(v)

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str | None) -> str | None:
        if v is not None:
            return validar_chave_acesso(v)
        return v


class NFCeResponse(BaseModel):
    """Resposta com dados da NFC-e emitida/consultada."""

    id: UUID
    empresa_id: UUID
    chave_acesso: str
    numero: int
    serie: int
    modelo: str = "65"
    status: str
    protocolo: str | None = None
    valor_total: float | None = None
    emitida_em: datetime | None = None
    autorizada_em: datetime | None = None
    xml_assinado: str | None = None
    xml_protocolado: str | None = None

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)
