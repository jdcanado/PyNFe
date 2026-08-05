"""Modelo NotaFiscal."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base, TimestampMixin, UUIDMixin


class NotaFiscal(UUIDMixin, TimestampMixin, Base):
    """Nota fiscal eletrônica (NF-e/NFC-e) emitida pela API."""

    __tablename__ = "notas_fiscais"
    __table_args__ = (Index("ix_notas_fiscais_empresa_status", "empresa_id", "status"),)

    empresa_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("empresas.id"), nullable=False
    )

    chave_acesso: Mapped[str] = mapped_column(String(44), unique=True, index=True, nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    serie: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    modelo: Mapped[str] = mapped_column(String(2), nullable=False, default="55")
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    protocolo: Mapped[str | None] = mapped_column(String(15))
    xml_assinado: Mapped[str | None] = mapped_column(Text)
    xml_protocolado: Mapped[str | None] = mapped_column(Text)
    valor_total: Mapped[float | None] = mapped_column()

    emitida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    autorizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    empresa: Mapped[Empresa] = relationship(back_populates="notas_fiscais")  # noqa: F821
