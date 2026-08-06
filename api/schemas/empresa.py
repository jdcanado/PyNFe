"""Schemas de empresa: upload de certificado digital."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
        return v
