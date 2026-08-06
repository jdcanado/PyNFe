"""App factory FastAPI com lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.config import get_settings
from api.core.logging import RequestLoggingMiddleware
from api.core.ratelimit import RateLimitMiddleware
from api.routers.auth import router as auth_router
from api.routers.empresa import router as empresa_router
from api.routers.gdpr import router as gdpr_router
from api.routers.gtin import router as gtin_router
from api.routers.nfce import router as nfce_router
from api.routers.nfe import router as nfe_router
from api.routers.sefaz import router as sefaz_router
from api.routers.tasks import router as tasks_router
from api.routers.webhooks import router as webhooks_router

settings = get_settings()

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa recursos (DB engine, Redis) ao subir."""
    from api.core.database import engine

    yield

    await engine.dispose()


def create_app() -> FastAPI:
    """Cria a aplicação FastAPI."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limit por API key (Vercel KV / Upstash Redis, sliding window)
    app.add_middleware(RateLimitMiddleware)

    # Log de requests (método, path, status, duração)
    app.add_middleware(RequestLoggingMiddleware)

    api_router = APIRouter(prefix=API_V1_PREFIX)

    @api_router.get("/health")
    async def health() -> dict:
        """Health check."""
        return {"status": "ok", "version": settings.version}

    api_router.include_router(auth_router)
    api_router.include_router(empresa_router)
    api_router.include_router(gdpr_router)
    api_router.include_router(gtin_router)
    api_router.include_router(nfe_router)
    api_router.include_router(nfce_router)
    api_router.include_router(sefaz_router)
    api_router.include_router(tasks_router)
    api_router.include_router(webhooks_router)
    app.include_router(api_router)

    return app


app = create_app()
