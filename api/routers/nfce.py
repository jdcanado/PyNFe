"""Rotas de NFC-e: emissão e consulta."""

from __future__ import annotations

from datetime import date, timedelta
from math import ceil

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.core.exceptions import DomainError, EmpresaNaoEncontrada, SefazError
from api.models import APIClient, NotaFiscal
from api.schemas.common import PaginatedResponse
from api.schemas.nfce import NFCeEmitirRequest, NFCeResponse
from api.schemas.nfe import NotaFiscalResumo
from api.services.nfce_service import emitir_nfce
from api.utils.crypto import hash_documento

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


@router.get("/listar", response_model=PaginatedResponse[NotaFiscalResumo])
async def listar(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    data_inicio: date | None = Query(default=None),  # noqa: B008
    data_fim: date | None = Query(default=None),  # noqa: B008
    destinatario: str | None = Query(default=None),
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PaginatedResponse[NotaFiscalResumo]:
    """Lista as NFC-e (modelo 65) da empresa com paginação e filtros."""
    query = select(NotaFiscal).where(
        NotaFiscal.empresa_id == client.empresa_id,
        NotaFiscal.modelo == "65",
    )

    if status:
        query = query.where(NotaFiscal.status == status.upper())
    if data_inicio:
        query = query.where(NotaFiscal.emitida_em >= data_inicio)
    if data_fim:
        query = query.where(NotaFiscal.emitida_em < data_fim + timedelta(days=1))
    if destinatario:
        # LGPD: o banco guarda apenas o hash do documento
        query = query.where(NotaFiscal.destinatario == hash_documento(destinatario))

    query = query.order_by(NotaFiscal.emitida_em.desc())

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    notas = result.scalars().all()

    return PaginatedResponse(
        items=[NotaFiscalResumo.model_validate(n, from_attributes=True) for n in notas],
        total=total,
        page=page,
        size=size,
        pages=ceil(total / size) if total else 0,
    )
