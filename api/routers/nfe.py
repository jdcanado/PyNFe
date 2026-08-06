"""Rotas de NF-e: emissão e listagem."""

from __future__ import annotations

from datetime import date, timedelta
from math import ceil

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.core.exceptions import DomainError, EmpresaNaoEncontrada, SefazError
from api.models import APIClient, NotaFiscal
from api.schemas.common import PaginatedResponse
from api.schemas.nfe import NFeEmitirResponse, NotaFiscalResumo
from api.schemas.nota_item import NotaFiscalSchema
from api.services.nfe_service import emitir_nfe

router = APIRouter(prefix="/nfe", tags=["nfe"])


@router.post("/emitir", response_model=NFeEmitirResponse)
async def emitir(
    payload: NotaFiscalSchema,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> NFeEmitirResponse:
    """Emite uma NF-e associada à empresa do client autenticado."""
    payload.empresa_id = client.empresa_id
    try:
        return await emitir_nfe(payload, homologacao=True, redis=redis, session=db)
    except EmpresaNaoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SefazError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except DomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/listar", response_model=PaginatedResponse[NotaFiscalResumo])
async def listar(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    data_inicio: date | None = Query(default=None),  # noqa: B008
    data_fim: date | None = Query(default=None),  # noqa: B008
    destinatario: str | None = Query(default=None),
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PaginatedResponse[NotaFiscalResumo]:
    """Lista as NF-e da empresa com paginação e filtros (ordem por emissão DESC)."""
    query = select(NotaFiscal).where(NotaFiscal.empresa_id == client.empresa_id)

    if status:
        query = query.where(NotaFiscal.status == status.upper())
    if data_inicio:
        query = query.where(NotaFiscal.emitida_em >= data_inicio)
    if data_fim:
        query = query.where(NotaFiscal.emitida_em < data_fim + timedelta(days=1))
    if destinatario:
        query = query.where(NotaFiscal.destinatario == destinatario)

    query = query.order_by(NotaFiscal.emitida_em.desc())

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    notas = result.scalars().all()

    return PaginatedResponse(
        items=[NotaFiscalResumo.model_validate(n, from_attributes=True) for n in notas],
        total=total,
        page=page,
        size=size,
        pages=ceil(total / size) if total else 0,
    )
