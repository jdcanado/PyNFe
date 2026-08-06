"""Rotas de status dos webservices SEFAZ por UF."""

from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.core.exceptions import CertificadoError, DomainError
from api.models import APIClient
from api.services.sefaz_service import UFS, verificar_status_todos, verificar_status_uf

router = APIRouter(prefix="/sefaz", tags=["sefaz"])


def _mapear_erros(exc: DomainError) -> HTTPException:
    """Traduz exceções de domínio para status codes HTTP."""
    if isinstance(exc, CertificadoError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/status/{uf}")
async def status_uf(
    uf: str,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> dict:
    """Status do webservice SEFAZ de uma UF (cache KV de 60s)."""
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"UF inválida: {uf}",
        )
    try:
        return await verificar_status_uf(db, redis, uf, client.empresa_id)
    except DomainError as exc:
        raise _mapear_erros(exc) from exc


@router.get("/status")
async def status_todos(
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> list[dict]:
    """Status de todas as 27 UFs em paralelo (cache KV de 60s por UF)."""
    try:
        return await verificar_status_todos(db, redis, client.empresa_id)
    except DomainError as exc:
        raise _mapear_erros(exc) from exc
