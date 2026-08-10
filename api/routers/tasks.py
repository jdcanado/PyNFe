"""Rotas internas dos crons da Vercel (poller e warmer).

Protegidas por `tasks_secret` (env var): chamadas externas (cron jobs, GitHub
Actions) devem enviar `Authorization: Bearer <tasks_secret>`. Se `tasks_secret`
nao estiver configurado (vazio), a protecao e desabilitada (dev local).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import get_db
from api.tasks.poller import processar_pendentes
from api.tasks.warmer import warm


def _verificar_tasks_secret(
    authorization: str = Header(default=""),
) -> None:
    """Valida o header Authorization contra o tasks_secret configurado.

    Se tasks_secret nao estiver configurado (vazio), permite acesso livre
    (compatibilidade com dev local sem secret).
    """
    settings = get_settings()
    if not settings.tasks_secret:
        return
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != settings.tasks_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/warmer")
async def warmer(
    _: None = Depends(_verificar_tasks_secret),
) -> dict:
    """Cron de aquecimento (a cada 5 min) — mantém a função quente."""
    return warm()


@router.api_route("/poller", methods=["GET", "POST"])
async def poller(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    _: None = Depends(_verificar_tasks_secret),
) -> dict:
    """Cron do poller (a cada 2 min) — processa notas em processamento.

    GET é o método usado pelos cron jobs da Vercel; POST mantido para uso
    manual/testes.
    """
    return await processar_pendentes(db)
