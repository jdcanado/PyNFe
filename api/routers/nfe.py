"""Rotas de NF-e: emissão."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.core.dependencies import get_current_client
from api.core.exceptions import DomainError, EmpresaNaoEncontrada, SefazError
from api.models import APIClient
from api.schemas.nfe import NFeEmitirResponse
from api.schemas.nota_item import NotaFiscalSchema
from api.services.nfe_service import emitir_nfe

router = APIRouter(prefix="/nfe", tags=["nfe"])


@router.post("/emitir", response_model=NFeEmitirResponse)
async def emitir(
    payload: NotaFiscalSchema,
    client: APIClient = Depends(get_current_client),  # noqa: B008
) -> NFeEmitirResponse:
    """Emite uma NF-e associada à empresa do client autenticado."""
    # `empresa_id` é derivado do client autenticado (ignora o valor do payload)
    payload.empresa_id = client.empresa_id
    try:
        return await emitir_nfe(payload, homologacao=True)
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
