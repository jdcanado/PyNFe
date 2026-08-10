"""Migração inicial do banco — cria todas as tabelas (idempotente).

Uso:
    PYTHONPATH=. python api/scripts/migrate.py

Usa o `DATABASE_URL` do ambiente/`api/.env` (Postgres em produção, SQLite em
dev local). Pode ser executado repetidamente sem erro.
"""

from __future__ import annotations

import asyncio


async def _run() -> None:
    from sqlalchemy import text

    import api.models  # noqa: F401  (registra todos os modelos)
    from api.core.database import engine
    from api.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # `create_all` não adiciona colunas em tabelas existentes. Para
        # Postgres, aplica ALTER TABLE idempotente para colunas que foram
        # adicionadas ao modelo depois da criação inicial da tabela.
        # Ex.: csc/csc_id (NFC-e/QR Code) na tabela `empresas`.
        if engine.dialect.name == "postgresql":
            await conn.execute(
                text(
                    "ALTER TABLE empresas "
                    "ADD COLUMN IF NOT EXISTS csc VARCHAR(36), "
                    "ADD COLUMN IF NOT EXISTS csc_id VARCHAR(6)"
                )
            )

    print("Migração concluída. Tabelas:", ", ".join(sorted(Base.metadata.tables)))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
