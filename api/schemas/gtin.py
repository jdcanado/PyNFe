"""Schemas de consulta de GTIN (tributação aproximada)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class GtinResponse(BaseModel):
    """Resultado de consulta de um GTIN."""

    codigo_gtin: str
    descricao: str | None = None
    ncm: str | None = None
    cest: str | None = None
    resultado_json: dict | None = None


class GtinLoteRequest(BaseModel):
    """Lote de códigos GTIN para consulta em lote."""

    codigos: list[str] = Field(min_length=1, max_length=50)

    @field_validator("codigos")
    @classmethod
    def _validar_codigos(cls, v: list[str]) -> list[str]:
        for codigo in v:
            if not codigo.isdigit() or len(codigo) not in (8, 12, 13, 14):
                raise ValueError("Cada GTIN deve ter 8, 12, 13 ou 14 dígitos numéricos")
        return v


class GtinLoteResponse(BaseModel):
    """Resposta de consulta em lote de GTINs."""

    resultados: list[GtinResponse]
    consultados: int = Field(ge=0)
    encontrados: int = Field(ge=0)
