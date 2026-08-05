"""Modelo APIClient."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base, TimestampMixin, UUIDMixin


class APIClient(UUIDMixin, TimestampMixin, Base):
    """Cliente de API autenticado via api_key."""

    __tablename__ = "api_clients"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    plano: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    empresa_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("empresas.id"), index=True, nullable=False
    )

    empresa: Mapped["Empresa"] = relationship(back_populates="api_clients")  # noqa: F821
