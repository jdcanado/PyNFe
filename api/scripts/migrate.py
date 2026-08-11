"""Migração do banco — cria tabelas e adiciona colunas novas (idempotente).

Uso (script):
    PYTHONPATH=. python api/scripts/migrate.py

Também expõe `migrar()` para o endpoint `POST /api/v1/admin/migrate`.
`Base.metadata.create_all` não altera tabelas existentes; as colunas novas
adicionadas ao modelo depois da criação inicial da tabela são aplicadas via
ALTER TABLE idempotente.
"""

from __future__ import annotations

import asyncio

# Colunas adicionadas à tabela `empresas` depois da criação inicial
_COLUNAS_EMPRESAS = (
    ("csc", "VARCHAR(36)"),
    ("csc_id", "VARCHAR(6)"),
    ("codigo_regime_tributario", "VARCHAR(2)"),
)

# ALTER COLUMN TYPE para colunas que tiveram o tamanho ampliado
# (ex.: protocolo/recibo da NFC-e podem ter mais dígitos que NF-e).
_ALTERACOES_TIPO = {
    "notas_fiscais": [
        ("protocolo", "VARCHAR(20)"),
        ("recibo", "VARCHAR(20)"),
    ],
}


async def migrar() -> list[str]:
    """Cria as tabelas e adiciona colunas novas (idempotente).

    Retorna a lista de tabelas do schema após a migração.
    """
    from sqlalchemy import text

    import api.models  # noqa: F401  (registra todos os modelos)
    from api.core.database import engine
    from api.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if engine.dialect.name == "postgresql":
            adicionar = ", ".join(
                f"ADD COLUMN IF NOT EXISTS {nome} {tipo}" for nome, tipo in _COLUNAS_EMPRESAS
            )
            await conn.execute(text(f"ALTER TABLE empresas {adicionar}"))
        elif engine.dialect.name == "sqlite":
            # SQLite não suporta ADD COLUMN IF NOT EXISTS: verifica via PRAGMA.
            existentes = {
                row[1]
                for row in (await conn.execute(text("PRAGMA table_info(empresas)"))).fetchall()
            }
            for nome, tipo in _COLUNAS_EMPRESAS:
                if nome not in existentes:
                    await conn.execute(text(f"ALTER TABLE empresas ADD COLUMN {nome} {tipo}"))

        # ALTER COLUMN TYPE: ampliações de tamanho (ex.: protocolo/recibo da NFC-e).
        # SQLite não enforça comprimento — só Postgres.
        if engine.dialect.name == "postgresql":
            for tabela, colunas in _ALTERACOES_TIPO.items():
                for coluna, tipo in colunas:
                    await conn.execute(
                        text(f"ALTER TABLE {tabela} ALTER COLUMN {coluna} TYPE {tipo}")
                    )

    return sorted(Base.metadata.tables)


async def _run() -> None:
    from api.core.database import engine

    tabelas = await migrar()
    print("Migração concluída. Tabelas:", ", ".join(tabelas))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
