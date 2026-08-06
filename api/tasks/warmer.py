"""Vercel Cron: mantém a função quente (a cada 5 min, ver `vercel.json`)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def warm() -> dict:
    """Resposta simples do warmer — evita cold start das funções."""
    return {"warm": True, "timestamp": datetime.now(timezone.utc).isoformat()}


async def handler(request: Any = None) -> dict:
    """Handler do cron da Vercel."""
    return warm()
