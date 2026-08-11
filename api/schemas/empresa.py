"""Schemas de empresa: criação (admin), atualização e upload de certificado."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import validar_cnpj, validar_csc, validar_csc_id, validar_uf


class CertificadoUploadResponse(BaseModel):
    """Resposta ao upload do certificado digital A1 da empresa."""

    empresa_id: UUID
    cnpj: str
    razao_social: str = Field(min_length=1, max_length=200)
    certificado_nome_arquivo: str
    validade: datetime | None = None
    mensagem: str = "Certificado enviado com sucesso"

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 14:
            raise ValueError("CNPJ deve ter exatamente 14 dígitos numéricos")
        return validar_cnpj(v)


class EmpresaCreateRequest(BaseModel):
    """Criação de empresa + API client (rota admin, plano free)."""

    cnpj: str
    razao_social: str = Field(min_length=1, max_length=200)
    nome_fantasia: str | None = Field(default=None, max_length=200)
    inscricao_estadual: str | None = Field(default=None, max_length=20)
    uf: str | None = Field(default=None, max_length=2)
    codigo_regime_tributario: str | None = Field(default=None, max_length=2)
    # NFC-e (QR Code) — opcionais já na criação
    csc: str | None = Field(default=None, max_length=36)
    csc_id: str | None = Field(default=None, max_length=6)
    client_name: str | None = Field(default=None, max_length=200)

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str) -> str:
        return validar_cnpj(v)

    @field_validator("uf")
    @classmethod
    def _validar_uf(cls, v: str | None) -> str | None:
        return validar_uf(v) if v is not None else None

    @field_validator("codigo_regime_tributario")
    @classmethod
    def _validar_crt(cls, v: str | None) -> str | None:
        if v is not None and v not in ("1", "2", "3", "4"):
            raise ValueError("codigo_regime_tributario deve ser 1, 2, 3 ou 4 (CRT)")
        return v

    @field_validator("csc")
    @classmethod
    def _validar_csc(cls, v: str | None) -> str | None:
        return validar_csc(v) if v is not None else None

    @field_validator("csc_id")
    @classmethod
    def _validar_csc_id(cls, v: str | None) -> str | None:
        return validar_csc_id(v) if v is not None else None


class EmpresaCreateResponse(BaseModel):
    """Resposta da criação: credenciais exibidas uma única vez."""

    empresa_id: UUID
    cnpj: str
    razao_social: str
    api_key: str
    api_secret: str
    api_key_prefix: str
    csc_id: str | None = None
    csc_mascarado: str | None = None
    mensagem: str = (
        "Empresa criada com sucesso. Guarde api_key e api_secret: não serão exibidos novamente."
    )


class EmpresaUpdateRequest(BaseModel):
    """Atualização parcial dos dados da empresa (token da própria empresa)."""

    nome_fantasia: str | None = Field(default=None, max_length=200)
    inscricao_estadual: str | None = Field(default=None, max_length=20)
    uf: str | None = Field(default=None, max_length=2)
    codigo_regime_tributario: str | None = Field(default=None, max_length=2)
    csc: str | None = Field(default=None, max_length=36)
    csc_id: str | None = Field(default=None, max_length=6)

    @field_validator("uf")
    @classmethod
    def _validar_uf(cls, v: str | None) -> str | None:
        return validar_uf(v) if v is not None else None

    @field_validator("codigo_regime_tributario")
    @classmethod
    def _validar_crt(cls, v: str | None) -> str | None:
        if v is not None and v not in ("1", "2", "3", "4"):
            raise ValueError("codigo_regime_tributario deve ser 1, 2, 3 ou 4 (CRT)")
        return v

    @field_validator("csc")
    @classmethod
    def _validar_csc(cls, v: str | None) -> str | None:
        return validar_csc(v) if v is not None else None

    @field_validator("csc_id")
    @classmethod
    def _validar_csc_id(cls, v: str | None) -> str | None:
        return validar_csc_id(v) if v is not None else None


class EmpresaUpdateResponse(BaseModel):
    """Dados atualizados da empresa (CSC mascarado na resposta)."""

    empresa_id: UUID
    cnpj: str
    razao_social: str
    nome_fantasia: str | None = None
    inscricao_estadual: str | None = None
    uf: str | None = None
    csc_id: str | None = None
    csc_mascarado: str | None = None
    mensagem: str = "Empresa atualizada com sucesso"
