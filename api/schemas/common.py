"""Schemas comuns da API: respostas paginadas, erros e validadores de formato."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def validar_cnpj(v: str) -> str:
    """Valida CNPJ com exatamente 14 dígitos numéricos."""
    if not v.isdigit() or len(v) != 14:
        raise ValueError("CNPJ deve ter exatamente 14 dígitos numéricos")
    return v


def validar_chave_acesso(v: str) -> str:
    """Valida chave de acesso com exatamente 44 dígitos numéricos."""
    if not v.isdigit() or len(v) != 44:
        raise ValueError("chave_acesso deve ter exatamente 44 dígitos numéricos")
    return v


def validar_uf(v: str) -> str:
    """Valida UF com 2 letras maiúsculas (ex.: SP, MG)."""
    if len(v) != 2 or not v.isalpha():
        raise ValueError("UF deve ter exatamente 2 letras")
    return v.upper()


class PaginatedResponse(BaseModel, Generic[T]):
    """Resposta paginada genérica para listagens da API."""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_more: bool = False


class ErrorResponse(BaseModel):
    """Corpo padrão de erro da API."""

    error: str
    detail: str | None = None
    code: str | None = None
