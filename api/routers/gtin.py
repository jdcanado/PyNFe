"""Rotas de consulta de GTIN (código de barras / tributação aproximada)."""

from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.models import APIClient
from api.schemas.gtin import GtinLoteRequest, GtinLoteResponse, GtinResponse
from api.services.gtin_service import consultar_individual, consultar_lote

router = APIRouter(prefix="/gtin", tags=["gtin"])

GTIN_LENGTHS = (8, 12, 13, 14)


@router.get("/consultar/{codigo}", response_model=GtinResponse)
async def consultar(
    codigo: str,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> GtinResponse:
    """Consulta um GTIN individualmente (cache KV 24h + SEFAZ SP)."""
    if not codigo.isdigit() or len(codigo) not in GTIN_LENGTHS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GTIN deve ter 8, 12, 13 ou 14 dígitos numéricos",
        )

    resultado = await consultar_individual(db, redis, codigo, empresa_id=client.empresa_id)
    return GtinResponse(**resultado)


@router.post("/consultar/lote", response_model=GtinLoteResponse)
async def consultar_lote_endpoint(
    payload: GtinLoteRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> GtinLoteResponse:
    """Consulta até 50 GTINs em paralelo."""
    resultados = await consultar_lote(db, redis, payload.codigos, empresa_id=client.empresa_id)
    return GtinLoteResponse(
        resultados=[GtinResponse(**r) for r in resultados],
        consultados=len(resultados),
        encontrados=sum(1 for r in resultados if r["encontrado"]),
    )
