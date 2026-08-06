"""Rotas de gestão de webhooks: configuração, histórico de entregas e teste."""

from __future__ import annotations

from math import ceil
from types import SimpleNamespace

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.models import APIClient, Empresa, WebhookLog
from api.schemas.common import PaginatedResponse
from api.schemas.webhook import (
    WebhookConfigRequest,
    WebhookConfigResponse,
    WebhookLogResponse,
    WebhookTestResponse,
)
from api.services.webhook_service import disparar_webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/config", response_model=WebhookConfigResponse)
async def configurar_webhook(
    payload: WebhookConfigRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> WebhookConfigResponse:
    """Atualiza `webhook_url` e/ou `webhook_secret` da empresa do client."""
    empresa = await db.get(Empresa, client.empresa_id)
    if empresa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa não encontrada",
        )
    if payload.webhook_url is not None:
        empresa.webhook_url = payload.webhook_url
    if payload.webhook_secret is not None:
        empresa.webhook_secret = payload.webhook_secret
    await db.commit()
    await db.refresh(empresa)

    return WebhookConfigResponse(
        webhook_url=empresa.webhook_url,
        webhook_secret=("********" if empresa.webhook_secret else None),
    )


@router.get("/logs", response_model=PaginatedResponse[WebhookLogResponse])
async def listar_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PaginatedResponse[WebhookLogResponse]:
    """Histórico de entregas de webhook da empresa (mais recentes primeiro)."""
    base = select(WebhookLog).where(WebhookLog.empresa_id == client.empresa_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    result = await db.execute(
        base.order_by(WebhookLog.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    registros = result.scalars().all()

    return PaginatedResponse(
        items=[WebhookLogResponse.model_validate(r, from_attributes=True) for r in registros],
        total=total,
        page=page,
        size=size,
        pages=ceil(total / size) if total else 0,
    )


@router.post("/test", response_model=WebhookTestResponse)
async def testar_webhook(
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> WebhookTestResponse:
    """Envia um evento de teste para a URL configurada da empresa."""
    nota_teste = SimpleNamespace(
        id=None,
        empresa_id=client.empresa_id,
        chave_acesso="",
        status="AUTORIZADA",
        modelo="55",
    )
    ok = await disparar_webhook(nota_teste, {"tipo": "teste"}, db, redis=redis)
    return WebhookTestResponse(ok=ok, event="nfe.autorizada")
