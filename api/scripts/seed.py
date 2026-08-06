"""Seed de dados de teste — APENAS staging (AMBIENTE=2).

Insere uma empresa + API client de teste no banco. Recusa executar fora do
ambiente de staging para nunca poluir produção.

Uso (staging):
    AMBIENTE=2 PYTHONPATH=. python api/scripts/seed.py

Variáveis opcionais: SEED_CNPJ, SEED_RAZAO_SOCIAL, SEED_UF, SEED_CLIENT_NAME.
"""

from __future__ import annotations

import asyncio
import os
import uuid


def _guard_ambiente_staging() -> None:
    """Bloqueia a execução se AMBIENTE não for 2 (staging)."""
    ambiente = os.environ.get("AMBIENTE", "")
    if ambiente != "2":
        raise SystemExit(
            f"Seed recusado: AMBIENTE={ambiente!r} (esperado '2' = staging). "
            "Nunca rode este script em produção."
        )


async def _run() -> None:
    _guard_ambiente_staging()

    from sqlalchemy import select

    from api.core.database import SessionFactory
    from api.core.security import hash_api_key
    from api.models import APIClient, Empresa

    cnpj = os.environ.get("SEED_CNPJ", "99999999000199")
    razao_social = os.environ.get("SEED_RAZAO_SOCIAL", "Empresa Staging LTDA")
    uf = os.environ.get("SEED_UF", "PR")
    client_name = os.environ.get("SEED_CLIENT_NAME", "Client Staging")

    async with SessionFactory() as db:
        empresa = (
            await db.execute(select(Empresa).where(Empresa.cnpj == cnpj))
        ).scalar_one_or_none()
        if empresa is None:
            empresa = Empresa(cnpj=cnpj, razao_social=razao_social, uf=uf)
            db.add(empresa)
            await db.flush()
            print(f"Empresa criada: {razao_social} ({cnpj})")
        else:
            print(f"Empresa já existente: {razao_social} ({cnpj})")

        api_key = f"pk_{uuid.uuid4().hex}"
        client = APIClient(
            name=client_name,
            api_key_hash=hash_api_key(api_key),
            api_key_prefix=api_key[:8],
            is_active=True,
            empresa_id=empresa.id,
        )
        db.add(client)
        await db.commit()

    print(f"API client criado: {client_name}")
    print(f"API key (guarde com segurança): {api_key}")


if __name__ == "__main__":
    asyncio.run(_run())
