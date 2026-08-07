"""Rotas de autenticação: token e refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import get_db
from api.core.security import (
    create_jwt_token,
    decode_jwt_token,
    verify_api_key,
)
from api.models import APIClient
from api.schemas.auth import TokenResponse

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    api_key: str = Header(...),
    api_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TokenResponse:
    """Gera um JWT a partir de api_key + api_secret válidos."""
    result = await db.execute(select(APIClient).where(APIClient.api_key_prefix == api_key))
    client = result.scalar_one_or_none()

    if client is None or not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_api_key(api_secret, client.api_key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_jwt_token(str(client.id), {"client": client.name})
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        api_key_prefix=client.api_key_prefix,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    authorization: str = Header(...),
) -> TokenResponse:
    """Emite um novo token a partir de um JWT válido."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_jwt_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    new_token = create_jwt_token(subject)
    return TokenResponse(
        access_token=new_token,
        expires_in=settings.jwt_expire_minutes * 60,
        api_key_prefix=settings.api_key_prefix,
    )


@router.get("/dbinfo")
async def dbinfo(db: AsyncSession = Depends(get_db)):  # noqa: B008
    """Diagnóstico: banco conectado e contagem de API clients."""
    import re

    from sqlalchemy import func, select, text

    from api.models import APIClient

    current_db = (await db.execute(text("SELECT current_database()"))).scalar()
    total = (await db.execute(select(func.count()).select_from(APIClient))).scalar()
    host = (await db.execute(text("SELECT inet_server_addr()::text"))).scalar()
    port = (await db.execute(text("SELECT inet_server_port()"))).scalar()
    from api.core.config import get_settings
    _s = get_settings()
    _url = _s.database_url
    _masked = re.sub(r"(//[^:]+:)[^@]+@", r"\1***@", _url) if _url else ""
    return {
        "database": current_db,
        "host": host,
        "port": port,
        "dbinfo_url": _masked,
        "api_clients": total,
        "prefixes": [r[0] for r in (await db.execute(select(APIClient.api_key_prefix))).all()],
    }
