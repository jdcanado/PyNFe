"""Exceções de domínio da API.

Os services levantam exceções de domínio (em vez de `ValueError`/`Exception`
genéricos) e os routers as mapeiam para status codes precisos.
"""

from __future__ import annotations


class DomainError(Exception):
    """Erro de negócio da API. A mensagem é segura para expor ao cliente."""


class CertificadoError(DomainError):
    """Falha relacionada ao certificado digital A1."""


class EmpresaNaoEncontrada(DomainError):
    """Empresa não encontrada no banco de dados."""


class EmpresaJaExiste(DomainError):
    """Já existe empresa cadastrada com o mesmo CNPJ."""


class SefazError(DomainError):
    """Falha na comunicação com a SEFAZ."""


class ValidacaoNegocioError(DomainError):
    """Violação de regra de negócio (ex.: empresa sem certificado cadastrado)."""


class NotaNaoEncontrada(DomainError):
    """Nota fiscal não encontrada no banco de dados."""


class ConflitoEstadoError(DomainError):
    """Conflito de estado da nota (ex.: tentativa de cancelar nota já cancelada)."""
