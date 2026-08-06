"""Modelo Empresa."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base, TimestampMixin, UUIDMixin


class Empresa(UUIDMixin, TimestampMixin, Base):
    """Empresa emitente de documentos fiscais."""

    __tablename__ = "empresas"

    cnpj: Mapped[str] = mapped_column(String(14), unique=True, index=True, nullable=False)
    razao_social: Mapped[str] = mapped_column(String(200), nullable=False)
    nome_fantasia: Mapped[Optional[str]] = mapped_column(String(200))
    inscricao_estadual: Mapped[Optional[str]] = mapped_column(String(20))
    uf: Mapped[Optional[str]] = mapped_column(String(2))

    # Certificado A1 (PEM)
    cert_pem: Mapped[Optional[str]] = mapped_column(String)
    key_pem: Mapped[Optional[str]] = mapped_column(String)
    certificado_senha: Mapped[Optional[str]] = mapped_column(String)
    certificado_blob_url: Mapped[Optional[str]] = mapped_column(String(500))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    api_clients: Mapped[list[APIClient]] = relationship(  # noqa: F821
        back_populates="empresa", lazy="selectin"
    )
    notas_fiscais: Mapped[list[NotaFiscal]] = relationship(  # noqa: F821
        back_populates="empresa", lazy="selectin"
    )
