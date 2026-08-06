"""Modelo NotaFiscal."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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
    natureza_operacao: Mapped[Optional[str]] = mapped_column(String(60))
    # LGPD: hash SHA-256 do documento do destinatário (não é dado pessoal reversível)
    destinatario: Mapped[Optional[str]] = mapped_column(String(64))
    # LGPD: documento do destinatário criptografado com Fernet (dado pessoal em repouso)
    destinatario_cpf_encrypted: Mapped[Optional[str]] = mapped_column(Text)

    protocolo: Mapped[Optional[str]] = mapped_column(String(15))
    # nRec do lote assíncrono (usado pelo poller para consultar o resultado)
    recibo: Mapped[Optional[str]] = mapped_column(String(15))
    xml_assinado: Mapped[Optional[str]] = mapped_column(Text)
    xml_protocolado: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB no Postgres; JSON no SQLite (testes)
    eventos: Mapped[Optional[list]] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=list
    )
    valor_total: Mapped[Optional[float]] = mapped_column()

    emitida_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    autorizada_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    empresa: Mapped[Empresa] = relationship(back_populates="notas_fiscais")  # noqa: F821
