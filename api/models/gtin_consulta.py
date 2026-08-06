"""Modelo GtinConsulta."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDMixin


class GtinConsulta(UUIDMixin, TimestampMixin, Base):
    """Resultado de consulta de GTIN (tributação aproximada)."""

    __tablename__ = "gtin_consultas"

    codigo_gtin: Mapped[str] = mapped_column(String(14), index=True, nullable=False)
    descricao: Mapped[Optional[str]] = mapped_column(String(200))
    ncm: Mapped[Optional[str]] = mapped_column(String(8))
    cest: Mapped[Optional[str]] = mapped_column(String(7))
    resultado_json: Mapped[Optional[str]] = mapped_column(Text)
