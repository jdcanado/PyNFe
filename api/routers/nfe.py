"""Rotas de NF-e: emissão."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.schemas.nfe import NFeEmitirResponse
from api.schemas.nota_item import NotaFiscalSchema
from api.services.nfe_service import emitir_nfe

router = APIRouter(prefix="/nfe", tags=["nfe"])


@router.post("/emitir", response_model=NFeEmitirResponse)
async def emitir(payload: NotaFiscalSchema) -> NFeEmitirResponse:
    """Emite uma NF-e: serializa, assina, envia à SEFAZ e persiste."""
    try:
        return await emitir_nfe(payload, homologacao=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
