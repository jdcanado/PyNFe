"""Rotas LGPD: anonimização de dados de destinatários (CPF/CNPJ).

A anonimização substitui o dado pessoal criptografado por ausência (mantém
apenas o hash SHA-256, que não é reversível) e preserva os XMLs fiscais por
obrigação legal de retenção (5 anos). Cada solicitação é registrada em
`gdpr_solicitacoes`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client
from api.core.logging import get_logger
from api.models import APIClient, GdprSolicitacao, NotaFiscal
from api.schemas.gdpr import GdprAnonimizarResponse, GdprSolicitacaoResponse
from api.utils.crypto import hash_documento

logger = get_logger("api.gdpr")

router = APIRouter(prefix="/gdpr", tags=["gdpr"])

DOCUMENTO_VALIDO_LENGTHS = (11, 14)


def _validar_documento(documento: str) -> str:
    """Valida CPF (11) ou CNPJ (14) numérico."""
    if not documento.isdigit() or len(documento) not in DOCUMENTO_VALIDO_LENGTHS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="documento deve ser CPF (11 dígitos) ou CNPJ (14 dígitos)",
        )
    return documento


@router.delete("/solicitante/{documento}", response_model=GdprAnonimizarResponse)
async def anonimizar_solicitante(
    documento: str,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GdprAnonimizarResponse:
    """Anonimiza os registros do CPF/CNPJ (mantém XMLs por obrigação fiscal)."""
    _validar_documento(documento)
    documento_hash = hash_documento(documento)

    result = await db.execute(
        select(NotaFiscal).where(
            NotaFiscal.empresa_id == client.empresa_id,
            NotaFiscal.destinatario == documento_hash,
        )
    )
    notas = list(result.scalars().all())

    xmls_mantidos = sum(1 for n in notas if n.xml_assinado or n.xml_protocolado)
    for nota in notas:
        # Remove o dado pessoal criptografado; mantém o hash e os XMLs
        nota.destinatario_cpf_encrypted = None
    await db.commit()

    solicitacao = GdprSolicitacao(
        empresa_id=client.empresa_id,
        documento_hash=documento_hash,
        status="processada",
        registros_anonimizados=len(notas),
    )
    db.add(solicitacao)
    await db.commit()
    await db.refresh(solicitacao)

    logger.info(
        "LGPD: anonimização %s (empresa %s): %d registros, %d XMLs mantidos",
        documento_hash[:12],
        client.empresa_id,
        len(notas),
        xmls_mantidos,
    )

    return GdprAnonimizarResponse(
        id=solicitacao.id,
        documento_hash=documento_hash,
        status=solicitacao.status,
        registros_anonimizados=len(notas),
        xmls_mantidos=xmls_mantidos,
    )


@router.get("/solicitacao/{solicitacao_id}", response_model=GdprSolicitacaoResponse)
async def status_solicitacao(
    solicitacao_id: UUID,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GdprSolicitacaoResponse:
    """Status de uma solicitação de anonimização (apenas da própria empresa)."""
    solicitacao = await db.get(GdprSolicitacao, solicitacao_id)
    if solicitacao is None or solicitacao.empresa_id != client.empresa_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitação não encontrada",
        )

    return GdprSolicitacaoResponse(
        id=solicitacao.id,
        documento_hash=solicitacao.documento_hash,
        status=solicitacao.status,
        registros_anonimizados=solicitacao.registros_anonimizados,
        created_at=solicitacao.created_at,
    )
