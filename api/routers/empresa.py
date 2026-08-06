"""Rotas de empresa: upload de certificado digital A1."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from api.schemas.empresa import CertificadoUploadResponse
from api.services.certificado_service import upload_certificado

router = APIRouter(prefix="/empresa", tags=["empresa"])


@router.post("/certificado", response_model=CertificadoUploadResponse)
async def enviar_certificado(
    empresa_id: UUID = Form(...),  # noqa: B008
    senha: str = Form(...),
    arquivo: UploadFile = File(...),  # noqa: B008
) -> CertificadoUploadResponse:
    """Recebe o PFX, criptografa e distribui nas 3 camadas (Blob/KV/Postgres)."""
    if not arquivo.filename or not arquivo.filename.lower().endswith(".pfx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado deve ser um certificado .pfx",
        )

    pfx_bytes = await arquivo.read()
    if not pfx_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo PFX está vazio",
        )

    try:
        return await upload_certificado(empresa_id, pfx_bytes, senha)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao processar o certificado: {exc}",
        ) from exc
