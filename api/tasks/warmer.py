"""Cron job: warmer para manter a função serverless aquecida."""

from __future__ import annotations


def warmer() -> dict:
    """Task de warm-up para evitar cold starts."""
    return {"status": "ok", "task": "warmer"}
