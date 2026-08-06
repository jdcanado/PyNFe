"""Modelo GdprSolicitacao — registro de solicitações de anonimização (LGPD)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDMixin


class GdprSolicitacao(UUIDMixin, TimestampMixin, Base):
    """Solicitação de anonimização de dados de um CPF/CNPJ.

    Colunas (conforme card): id, documento_hash, status, created_at.
    `empresa_id` isola as solicitações por empresa (o client só vê as suas).
    """

    __tablename__ = "gdpr_solicitacoes"

    empresa_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("empresas.id"), nullable=False, index=True
    )
    documento_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processada")
    registros_anonimizados: Mapped[int] = mapped_column(default=0, nullable=False)
