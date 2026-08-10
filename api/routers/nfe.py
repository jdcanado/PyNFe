"""Rotas de NF-e: emissão e listagem."""

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
from api.schemas.nfe import (
    CadastroResponse,
    CancelarRequest,
    CartaCorrecaoRequest,
    ConsultarNotaRequest,
    ConsultarNotaResponse,
    DistribuicaoRequest,
    DistribuicaoResponse,
    EventoResponse,
    InutilizarRequest,
    InutilizarResponse,
    NFeEmitirResponse,
    NotaFiscalResumo,
    OperacaoNaoRealizadaRequest,
)
from api.schemas.nota_item import NotaFiscalSchema
from api.services.nfe_service import (
    cancelar_nota,
    carta_correcao_nota,
    consultar_cadastro,
    consultar_distribuicao,
    consultar_nota_sefaz,
    emitir_nfe,
    inutilizar_nota,
    operacao_nao_realizada,
)
from api.utils.crypto import hash_documento

router = APIRouter(prefix="/nfe", tags=["nfe"])


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


@router.post("/emitir", response_model=NFeEmitirResponse)
async def emitir(
    payload: NotaFiscalSchema,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> NFeEmitirResponse:
    """Emite uma NF-e associada à empresa do client autenticado."""
    payload.empresa_id = client.empresa_id
    try:
        return await emitir_nfe(payload, homologacao=True, redis=redis, session=db)
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
    """Lista as NF-e da empresa com paginação e filtros (ordem por emissão DESC)."""
    query = select(NotaFiscal).where(NotaFiscal.empresa_id == client.empresa_id)

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


@router.post("/cancelar", response_model=EventoResponse)
async def cancelar(
    payload: CancelarRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> EventoResponse:
    """Cancela uma NF-e (evento 110111) e atualiza o status para CANCELADA."""
    return await _executar_evento(
        cancelar_nota(
            db,
            redis,
            client.empresa_id,
            payload.chave_acesso,
            payload.justificativa,
            protocolo=payload.protocolo,
            modelo="55",
        )
    )


@router.post("/carta-correcao", response_model=EventoResponse)
async def carta_correcao(
    payload: CartaCorrecaoRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> EventoResponse:
    """Envia carta de correção (evento 110110) para uma NF-e autorizada."""
    return await _executar_evento(
        carta_correcao_nota(
            db,
            redis,
            client.empresa_id,
            payload.chave_acesso,
            payload.correcao,
            modelo="55",
        )
    )


@router.post("/inutilizar", response_model=InutilizarResponse)
async def inutilizar(
    payload: InutilizarRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> InutilizarResponse:
    """Inutiliza uma faixa de numeração de NF-e junto à SEFAZ."""
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
            modelo="55",
        )
    )


@router.post("/consultar", response_model=ConsultarNotaResponse)
async def consultar_sefaz(
    payload: ConsultarNotaRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> ConsultarNotaResponse:
    """Consulta a situação de uma NF-e na SEFAZ pela chave de acesso."""
    return await _executar_evento(
        consultar_nota_sefaz(db, redis, client.empresa_id, payload.chave_acesso, modelo="55")
    )


@router.post("/distribuicao", response_model=DistribuicaoResponse)
async def distribuicao(
    payload: DistribuicaoRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> DistribuicaoResponse:
    """Consulta a distribuição de DF-e no ambiente nacional (NFeDistribuicaoDFe)."""
    return await _executar_evento(
        consultar_distribuicao(
            db,
            redis,
            client.empresa_id,
            cnpj=payload.cnpj,
            cpf=payload.cpf,
            chave=payload.chave,
            nsu=payload.nsu,
            consulta_nsu_especifico=payload.consulta_nsu_especifico,
        )
    )


@router.get("/cadastro", response_model=CadastroResponse)
async def cadastro(
    uf: str = Query(..., min_length=2, max_length=2),
    documento: str = Query(...),
    tipo: str = Query(default="CNPJ", pattern="^(CNPJ|CPF|IE)$"),
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> CadastroResponse:
    """Consulta o cadastro de contribuintes na SEFAZ (CadConsultaCadastro4)."""
    return await _executar_evento(
        consultar_cadastro(
            db,
            redis,
            client.empresa_id,
            uf=uf.upper(),
            documento=documento,
            tipo=tipo,
        )
    )


@router.post("/operacao-nao-realizada", response_model=EventoResponse)
async def operacao_nao_realizada_evento(
    payload: OperacaoNaoRealizadaRequest,
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> EventoResponse:
    """Registra o evento de operação não realizada (110112) para uma NF-e autorizada."""
    return await _executar_evento(
        operacao_nao_realizada(
            db,
            redis,
            client.empresa_id,
            payload.chave_acesso,
            payload.justificativa,
            modelo="55",
        )
    )
