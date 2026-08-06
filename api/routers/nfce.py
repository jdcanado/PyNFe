"""Rotas de NFC-e: emissão e consulta."""

from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.core.exceptions import DomainError, EmpresaNaoEncontrada, SefazError
from api.models import APIClient, NotaFiscal
from api.schemas.nfce import NFCeEmitirRequest, NFCeResponse
from api.services.nfce_service import emitir_nfce

router = APIRouter(prefix="/nfce", tags=["nfce"])


@router.post("/emitir", response_model=NFCeResponse)
async def emitir(
    payload: NFCeEmitirRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> NFCeResponse:
    """Emite uma NFC-e associada à empresa do client autenticado."""
    payload.empresa_id = client.empresa_id
    try:
        return await emitir_nfce(payload, homologacao=True, redis=redis, session=db)
    except EmpresaNaoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SefazError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except DomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/consultar/{chave}", response_model=NFCeResponse)
async def consultar(
    chave: str,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> NFCeResponse:
    """Consulta uma NFC-e pela chave de acesso (44 dígitos)."""
    if len(chave) != 44 or not chave.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chave deve ter exatamente 44 dígitos",
        )

    result = await db.execute(
        select(NotaFiscal).where(
            NotaFiscal.chave_acesso == chave,
            NotaFiscal.empresa_id == client.empresa_id,
        )
    )
    nota = result.scalar_one_or_none()
    if nota is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NFC-e não encontrada",
        )

    return NFCeResponse(
        id=nota.id,
        empresa_id=nota.empresa_id,
        chave_acesso=nota.chave_acesso,
        numero=nota.numero,
        serie=nota.serie,
        modelo=nota.modelo,
        status=nota.status,
        protocolo=nota.protocolo,
        valor_total=nota.valor_total,
        emitida_em=nota.emitida_em,
        autorizada_em=nota.autorizada_em,
        xml_assinado=nota.xml_assinado,
        xml_protocolado=nota.xml_protocolado,
    )
