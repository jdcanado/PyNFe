"""Rotas de empresa: upload de certificado digital A1."""

from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.dependencies import get_current_client, get_redis_dep
from api.core.exceptions import DomainError, EmpresaNaoEncontrada, SefazError
from api.models import APIClient
from api.schemas.empresa import CertificadoUploadResponse
from api.services.certificado_service import upload_certificado

router = APIRouter(prefix="/empresa", tags=["empresa"])


@router.post("/certificado", response_model=CertificadoUploadResponse)
async def enviar_certificado(
    senha: str = Form(...),
    arquivo: UploadFile = File(...),  # noqa: B008
    client: APIClient = Depends(get_current_client),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis: redis_async.Redis = Depends(get_redis_dep),  # noqa: B008
) -> CertificadoUploadResponse:
    """Recebe o PFX, criptografa e distribui nas 3 camadas (Blob/KV/Postgres).

    O certificado é associado à empresa do client autenticado (não aceita
    `empresa_id` do request).
    """
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
        return await upload_certificado(
            client.empresa_id, pfx_bytes, senha, redis=redis, session=db
        )
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
