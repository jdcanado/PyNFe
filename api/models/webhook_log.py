"""Modelo WebhookLog — registro de tentativas de entrega de webhooks."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDMixin


class WebhookLog(UUIDMixin, TimestampMixin, Base):
    """Registro de uma tentativa de entrega de webhook.

    Colunas (conforme card): id, nota_id, event, url, status_code, tentativa,
    sucesso, created_at. `empresa_id` permite isolar o histórico por empresa.
    """

    __tablename__ = "webhook_logs"
    __table_args__ = (Index("ix_webhook_logs_empresa_created", "empresa_id", "created_at"),)

    empresa_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("empresas.id"), nullable=False
    )
    nota_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("notas_fiscais.id")
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    tentativa: Mapped[int] = mapped_column(Integer, nullable=False)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
