"""Schemas de NF-e (modelo 55): emissão, resposta, cancelamento e inutilização."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import validar_chave_acesso, validar_cnpj


class NFeEmitirRequest(BaseModel):
    """Requisição de emissão de NF-e."""

    empresa_id: UUID
    cnpj: str = Field(description="CNPJ do emitente (14 dígitos)")
    numero: int = Field(ge=1, le=999_999_999)
    serie: int = Field(default=1, ge=0, le=999)
    natureza_operacao: str = Field(min_length=1, max_length=60)
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


class NFeResponse(BaseModel):
    """Resposta com dados da NF-e emitida/consultada."""

    id: UUID
    empresa_id: UUID
    chave_acesso: str
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

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)


class CancelarRequest(BaseModel):
    """Requisição de cancelamento de NF-e."""

    chave_acesso: str
    protocolo: str = Field(min_length=15, max_length=15)
    justificativa: str = Field(min_length=15, max_length=255)

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)


class InutilizarRequest(BaseModel):
    """Requisição de inutilização de numeração de NF-e."""

    cnpj: str
    ano: int = Field(ge=2000, le=2100)
    serie: int = Field(ge=0, le=999)
    numero_inicial: int = Field(ge=1)
    numero_final: int = Field(ge=1)
    justificativa: str = Field(min_length=15, max_length=255)

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str) -> str:
        return validar_cnpj(v)

    @field_validator("numero_final")
    @classmethod
    def _validar_intervalo(cls, v: int, info) -> int:
        if "numero_inicial" in info.data and v < info.data["numero_inicial"]:
            raise ValueError("numero_final deve ser >= numero_inicial")
        return v


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
