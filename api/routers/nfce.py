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
from api.core.exceptions import (
    ConflitoEstadoError,
    DomainError,
    EmpresaNaoEncontrada,
    NotaNaoEncontrada,
    SefazError,
)
from api.models import APIClient, NotaFiscal
from api.schemas.common import PaginatedResponse
from api.schemas.nfce import NFCeEmitirRequest, NFCeResponse
from api.schemas.nfe import (
    CancelarRequest,
    CartaCorrecaoRequest,
    EventoResponse,
    InutilizarRequest,
    InutilizarResponse,
    NotaFiscalResumo,
)
from api.services.nfce_service import emitir_nfce
from api.services.nfe_service import cancelar_nota, carta_correcao_nota, inutilizar_nota

router = APIRouter(prefix="/nfce", tags=["nfce"])


async def _executar_evento(coro) -> EventoResponse | InutilizarResponse:
    """Executa a coroutine do service mapeando exceções de domínio para HTTP."""
    try:
        return await coro
    except NotaNaoEncontrada as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflitoEstadoError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmpresaNaoEncontrada as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SefazError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        query = query.where(NotaFiscal.destinatario == destinatario)

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


@router.post("/cancelar", response_model=EventoResponse)
async def cancelar(
    payload: CancelarRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> EventoResponse:
    """Cancela uma NFC-e (evento 110111) e atualiza o status para CANCELADA."""
    return await _executar_evento(
        cancelar_nota(
            db,
            redis,
            client.empresa_id,
            payload.chave_acesso,
            payload.justificativa,
            protocolo=payload.protocolo,
            modelo="65",
        )
    )


@router.post("/carta-correcao", response_model=EventoResponse)
async def carta_correcao(
    payload: CartaCorrecaoRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> EventoResponse:
    """Envia carta de correção (evento 110110) para uma NFC-e autorizada."""
    return await _executar_evento(
        carta_correcao_nota(
            db,
            redis,
            client.empresa_id,
            payload.chave_acesso,
            payload.correcao,
            modelo="65",
        )
    )


@router.post("/inutilizar", response_model=InutilizarResponse)
async def inutilizar(
    payload: InutilizarRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> InutilizarResponse:
    """Inutiliza uma faixa de numeração de NFC-e junto à SEFAZ."""
    return await _executar_evento(
        inutilizar_nota(
            db,
            redis,
            client.empresa_id,
            cnpj=payload.cnpj,
            serie=payload.serie,
            numero_inicial=payload.numero_inicial,
            numero_final=payload.numero_final,
            justificativa=payload.justificativa,
            ano=payload.ano,
            modelo="65",
        )
    )
