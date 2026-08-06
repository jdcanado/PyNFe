"""Schemas de GDPR (LGPD): anonimização e status de solicitações."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GdprAnonimizarResponse(BaseModel):
    """Resultado da anonimização de um CPF/CNPJ."""

    id: UUID
    documento_hash: str
    status: str
    registros_anonimizados: int
    xmls_mantidos: int


class GdprSolicitacaoResponse(BaseModel):
    """Status de uma solicitação de anonimização."""

    id: UUID
    documento_hash: str
    status: str
    registros_anonimizados: int
    created_at: datetime
