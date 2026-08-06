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
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=2,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
    echo=settings.debug,
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency do FastAPI que fornece uma sessão async."""
    async with SessionFactory() as session:
        yield session
