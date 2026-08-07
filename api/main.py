"""App factory FastAPI com lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.config import get_settings
from api.core.logging import RequestLoggingMiddleware
from api.core.ratelimit import RateLimitMiddleware
from api.routers.admin import router as admin_router
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
    """Inicializa recursos (DB engine, Redis) ao subir.

    Cria as tabelas automaticamente (idempotente — não recria as que já existem).
    """
    from api.core.database import engine

    if engine is not None:
        import api.models  # noqa: F401  (registra todos os modelos)
        from api.models.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    yield

    if engine is not None:
        await engine.dispose()


TAGS_PT_BR = [
    {"name": "auth", "description": "Autenticação: geração e validação de tokens de acesso."},
    {"name": "empresa", "description": "Empresas emitentes e upload de certificado digital A1."},
    {
        "name": "nfe",
        "description": "Emissão, listagem, cancelamento e inutilização de NF-e (modelo 55).",
    },
    {"name": "nfce", "description": "Emissão, consulta e eventos de NFC-e (modelo 65)."},
    {"name": "gtin", "description": "Consulta de GTIN (código de barras / tributação aproximada)."},
    {"name": "sefaz", "description": "Status dos webservices SEFAZ por UF."},
    {"name": "webhooks", "description": "Configuração, histórico e teste de webhooks."},
    {"name": "admin", "description": "Métricas e gestão administrativa da API."},
    {"name": "gdpr", "description": "Solicitações LGPD: anonimização de dados pessoais."},
    {"name": "tasks", "description": "Tarefas internas (crons da Vercel)."},
]


def create_app() -> FastAPI:
    """Cria a aplicação FastAPI."""
    app = FastAPI(
        title="PyNFe API",
        description="API REST para emissão de NF-e, NFC-e e consulta GTIN. "
        "Documentação completa em docs.api.pynfe.com.br",
        version="1.0.0",
        openapi_tags=TAGS_PT_BR,
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

    api_router.include_router(admin_router)
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
