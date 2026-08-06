"""Rotas administrativas: métricas e gestão de API clients.

Endpoints protegidos por `plano == "admin"` (403 caso contrário).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import get_db
from api.core.dependencies import get_current_client
from api.models import APIClient, NotaFiscal

router = APIRouter(prefix="/admin", tags=["admin"])


async def _get_current_admin(
    client: APIClient = Depends(get_current_client),  # noqa: B008
) -> APIClient:
    """Exige um API client com plano `admin`."""
    if client.plano != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores",
        )
    return client


@router.get("/estatisticas")
async def estatisticas(
    client: APIClient = Depends(_get_current_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """Métricas da empresa: notas hoje, taxa de autorização, top clients e rate limit."""
    empresa_id = client.empresa_id
    hoje = datetime.now(timezone.utc).date()

    total_hoje = (
        await db.execute(
            select(func.count())
            .select_from(NotaFiscal)
            .where(
                NotaFiscal.empresa_id == empresa_id,
                func.date(NotaFiscal.emitida_em) == hoje,
            )
        )
    ).scalar_one()

    total_geral = (
        await db.execute(
            select(func.count()).select_from(NotaFiscal).where(NotaFiscal.empresa_id == empresa_id)
        )
    ).scalar_one()

    autorizadas = (
        await db.execute(
            select(func.count())
            .select_from(NotaFiscal)
            .where(
                NotaFiscal.empresa_id == empresa_id,
                NotaFiscal.status == "AUTORIZADA",
            )
        )
    ).scalar_one()

    taxa_autorizacao = round(autorizadas / total_geral * 100, 1) if total_geral else 0.0

    top_clients = (
        await db.execute(
            select(APIClient.name, func.count(NotaFiscal.id).label("notas"))
            .join(NotaFiscal, NotaFiscal.empresa_id == APIClient.empresa_id)
            .where(APIClient.empresa_id == empresa_id)
            .group_by(APIClient.id, APIClient.name)
            .order_by(func.count(NotaFiscal.id).desc())
            .limit(5)
        )
    ).all()

    return {
        "empresa_id": str(empresa_id),
        "total_notas_hoje": total_hoje,
        "total_notas": total_geral,
        "taxa_autorizacao_percent": taxa_autorizacao,
        "top_api_clients": [{"nome": nome, "notas": qtd} for nome, qtd in top_clients],
        "rate_limit_enabled": get_settings().ratelimit_enabled,
    }


@router.get("/api-clients")
async def listar_api_clients(
    client: APIClient = Depends(_get_current_admin),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[dict]:
    """Lista todos os API clients da empresa do admin."""
    result = await db.execute(
        select(APIClient).where(APIClient.empresa_id == client.empresa_id).order_by(APIClient.name)
    )
    return [
        {
            "id": str(c.id),
            "nome": c.name,
            "plano": c.plano,
            "ativo": c.is_active,
        }
        for c in result.scalars().all()
    ]
