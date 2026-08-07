"""Configuração do banco de dados async (SQLAlchemy)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.core.config import get_settings

settings = get_settings()

# Configuração serverless-friendly (Neon/Postgres):
# - pool_pre_ping: valida conexões ociosas antes de usar
# - pool_recycle: recicla conexões antes do idle timeout do Neon
# - statement_cache_size=0: compatível com o PgBouncer (transaction mode)
#
# Em dev local (SQLite) os connect_args do asyncpg não se aplicam.
# Engine criado apenas se DATABASE_URL estiver configurada (evita
# ArgumentError no import do app na Vercel sem env vars).
if settings.database_url:
    url = settings.database_url
    # Adaptação automática da URL do Neon para asyncpg:
    # - postgresql://... → postgresql+asyncpg://...
    # - sslmode=require → ssl=require (asyncpg não aceita sslmode)
    # - remove channel_binding=... (não suportado pelo asyncpg)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=require" in url and "?ssl=" not in url:
        url = url.replace("sslmode=require", "ssl=require")
    # Remove channel_binding sem corromper o formato da URL
    url = url.replace("channel_binding=require&", "").replace("?channel_binding=require", "?")

    _connect_args: dict = {}
    if url.startswith("postgresql"):
        _connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }

    engine = create_async_engine(
        url,
        pool_size=settings.database_pool_size,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=_connect_args,
        echo=settings.debug,
    )

    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
else:
    engine = None
    SessionFactory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency do FastAPI que fornece uma sessão async."""
    if SessionFactory is None:
        raise RuntimeError("DATABASE_URL não configurada no ambiente")
    async with SessionFactory() as session:
        yield session
