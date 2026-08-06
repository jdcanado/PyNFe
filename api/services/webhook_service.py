"""Serviço de webhooks — notifica consumidores sobre finalização de notas.

O `disparar_webhook` é uma camada auxiliar: falhas de webhook (ou ausência
de `webhook_url`) não interrompem o poller.
"""

from __future__ import annotations

from typing import Any

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger("api.webhook_service")


async def disparar_webhook(nota: Any, resultado: dict) -> bool:
    """Dispara o webhook de finalização da nota (POST JSON para `webhook_url`).

    Retorna False (sem levantar exceção) quando a URL não está configurada ou
    a chamada falha.
    """
    url = get_settings().webhook_url
    if not url:
        logger.info(
            "webhook_url não configurado; pulando webhook da nota %s",
            getattr(nota, "id", None),
        )
        return False

    payload = {
        "nota_id": str(nota.id),
        "chave_acesso": nota.chave_acesso,
        "status": nota.status,
        "resultado": resultado,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao disparar webhook: %s", exc)
        return False
