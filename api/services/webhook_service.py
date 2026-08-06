"""Serviço de webhooks — entrega de notificações com retry, assinatura HMAC e log.

Fluxo:
1. Resolve URL e segredo (empresa → fallback global do Settings).
2. Monta o payload com o evento (ex.: `nfe.autorizada`).
3. Assina o payload com HMAC-SHA256 (`X-Webhook-Signature`).
4. Entrega com retry de backoff exponencial: 3 tentativas (1s, 5s, 25s),
   timeout de 10s por POST.
5. Registra cada tentativa em `webhook_logs`.

Falhas de webhook (ou ausência de URL) não interrompem o chamador (poller).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger("api.webhook_service")

# Backoff exponencial entre tentativas (em segundos)
RETRY_DELAYS = (1, 5, 25)
WEBHOOK_TIMEOUT = 10  # segundos
SIGNATURE_HEADER = "X-Webhook-Signature"

# Eventos suportados (modelo, status) -> nome do evento
_EVENTO_POR_STATUS = {
    ("55", "AUTORIZADA"): "nfe.autorizada",
    ("55", "REJEITADA"): "nfe.rejeitada",
    ("55", "CANCELADA"): "nfe.cancelada",
    ("65", "AUTORIZADA"): "nfce.autorizada",
}


def _evento_para(nota: Any) -> str:
    """Mapeia (modelo, status) da nota para o nome do evento webhook."""
    modelo = str(getattr(nota, "modelo", "55"))
    status = str(getattr(nota, "status", "")).upper()
    return _EVENTO_POR_STATUS.get((modelo, status), f"nota.{status.lower() or 'desconhecido'}")


def _assinar_payload(payload: dict, secret: str) -> str:
    """Calcula HMAC-SHA256 do payload canônico (JSON compacto com chaves ordenadas)."""
    corpo = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()


async def _registrar_log(
    db: Any,
    *,
    empresa_id: Any,
    nota_id: Any,
    event: str,
    url: str,
    status_code: int | None,
    tentativa: int,
    sucesso: bool,
) -> None:
    """Grava uma tentativa em `webhook_logs` (commit na sessão recebida)."""
    from api.models import WebhookLog

    db.add(
        WebhookLog(
            empresa_id=empresa_id,
            nota_id=nota_id,
            event=event,
            url=url,
            status_code=status_code,
            tentativa=tentativa,
            sucesso=sucesso,
        )
    )
    await db.commit()


async def disparar_webhook(
    nota: Any,
    resultado: dict,
    db: Any,
    redis: Any | None = None,
    *,
    delays: tuple[float, ...] | None = None,
) -> bool:
    """Entrega o webhook com retry, assinatura HMAC e registro em `webhook_logs`.

    - URL/segredo: empresa do `nota.empresa_id`, com fallback para o Settings.
    - Retry: 3 tentativas com backoff exponencial (1s, 5s, 25s); `delays`
      injetável para testes.
    - Cada tentativa é registrada no banco (`sucesso=True` em HTTP 2xx).

    Retorna True se alguma tentativa obteve sucesso.
    """
    from api.models import Empresa

    empresa_id = getattr(nota, "empresa_id", None)
    empresa = await db.get(Empresa, empresa_id) if empresa_id else None

    url = (
        empresa.webhook_url if empresa and empresa.webhook_url else None
    ) or get_settings().webhook_url
    secret = (
        empresa.webhook_secret if empresa and empresa.webhook_secret else None
    ) or get_settings().webhook_secret
    if not url:
        logger.info(
            "webhook_url não configurado; pulando evento da nota %s",
            getattr(nota, "id", None),
        )
        return False

    event = _evento_para(nota)
    payload = {
        "event": event,
        "nota_id": str(getattr(nota, "id", None)),
        "chave_acesso": getattr(nota, "chave_acesso", ""),
        "status": getattr(nota, "status", ""),
        "resultado": resultado,
    }
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = _assinar_payload(payload, secret)

    delays = delays or RETRY_DELAYS
    for tentativa, atraso in enumerate(delays, start=1):
        status_code = None
        sucesso = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, json=payload, headers=headers, timeout=WEBHOOK_TIMEOUT
                )
            status_code = resp.status_code
            sucesso = 200 <= resp.status_code < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tentativa %d do webhook falhou: %s", tentativa, exc)

        await _registrar_log(
            db,
            empresa_id=empresa_id,
            nota_id=getattr(nota, "id", None),
            event=event,
            url=url,
            status_code=status_code,
            tentativa=tentativa,
            sucesso=sucesso,
        )
        if sucesso:
            return True
        if atraso > 0:
            await asyncio.sleep(atraso)

    return False
