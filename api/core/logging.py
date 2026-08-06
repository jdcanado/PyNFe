"""Logging estruturado da API.

- `get_logger` retorna um logger configurado pelo nível de `settings.log_level`.
- `RequestLoggingMiddleware` registra método, path, status e duração de cada
  request HTTP.
"""

from __future__ import annotations

import logging
import sys
import time

from starlette.middleware.base import BaseHTTPMiddleware

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_logging_configured = False


def configure_logging() -> None:
    """Configura o logging raiz com o nível de `settings.log_level` (lazy)."""
    global _logging_configured
    if _logging_configured:
        return

    from api.core.config import get_settings

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger da API com a configuração padrão aplicada."""
    configure_logging()
    return logging.getLogger(name)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Registra cada request HTTP (método, path, status e duração)."""

    async def dispatch(self, request, call_next):
        logger = get_logger("api.request")
        inicio = time.monotonic()
        response = await call_next(request)
        duracao_ms = (time.monotonic() - inicio) * 1000
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duracao_ms,
        )
        return response
