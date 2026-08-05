"""Cron job: poller de documentos fiscais."""

from __future__ import annotations


def poller() -> dict:
    """Task de polling para processar documentos pendentes."""
    return {"status": "ok", "task": "poller"}
