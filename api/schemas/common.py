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


def validar_csc(v: str) -> str:
    """Valida o CSC (Código de Segurança do Contribuinte) — 36 caracteres.

    Aceita alfanuméricos e hífens: algumas SEFAZ emitem o CSC de homologação
    no formato UUID (ex.: `a3ce282f-2bf1-4b64-a55b-b4f1faa39683`).
    """
    if len(v) != 36 or not all(c.isalnum() or c == "-" for c in v):
        raise ValueError("CSC deve ter exatamente 36 caracteres (alfanuméricos ou com hífens)")
    return v


def validar_csc_id(v: str) -> str:
    """Valida o CSC ID (identificador do CSC na SEFAZ) — 6 dígitos numéricos."""
    if not v.isdigit() or len(v) != 6:
        raise ValueError("CSC ID deve ter exatamente 6 dígitos numéricos")
    return v


class PaginatedResponse(BaseModel, Generic[T]):
    """Resposta paginada genérica para listagens da API."""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)


class ErrorResponse(BaseModel):
    """Corpo padrão de erro da API."""

    error: str
    detail: str | None = None
    code: str | None = None
