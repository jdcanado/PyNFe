"""Rotas internas dos crons da Vercel (poller e warmer).

Endpoints sem autenticação: são chamados pelos cron jobs da Vercel
(`vercel.json`), que não enviam token de API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.tasks.poller import processar_pendentes
from api.tasks.warmer import warm

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/warmer")
async def warmer() -> dict:
    """Cron de aquecimento (a cada 5 min) — mantém a função quente."""
    return warm()


@router.api_route("/poller", methods=["GET", "POST"])
async def poller(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """Cron do poller (a cada 2 min) — processa notas em processamento.

    GET é o método usado pelos cron jobs da Vercel; POST mantido para uso
    manual/testes.
    """
    return await processar_pendentes(db)
