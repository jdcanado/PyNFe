"""Serviço de gestão de empresas: criação (admin) e atualização (token)."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import select

from api.core.config import get_settings
from api.core.exceptions import EmpresaJaExiste, EmpresaNaoEncontrada
from api.core.security import hash_api_key
from api.models import APIClient, Empresa
from api.schemas.empresa import (
    EmpresaCreateRequest,
    EmpresaCreateResponse,
    EmpresaUpdateRequest,
    EmpresaUpdateResponse,
)
from api.services.certificado_service import _session_ctx

PLANO_PADRAO = "free"


def mascarar_csc(csc: str | None) -> str | None:
    """Mascara o CSC mantendo os 4 primeiros caracteres visíveis."""
    if not csc:
        return None
    return csc[:4] + "*" * (len(csc) - 4)


def _gerar_credenciais() -> tuple[str, str, str]:
    """Gera (api_key, api_secret, api_key_prefix) no padrão do seed.

    - `api_key`: identificador público (prefixo `pnf_` + 4 hex), enviado no
      `POST /auth/token` como `api_key` (busca pelo `api_key_prefix`).
    - `api_secret`: segredo validado por bcrypt contra `api_key_hash`.
    """
    api_key = f"{get_settings().api_key_prefix}{secrets.token_hex(2)}"
    api_secret = secrets.token_urlsafe(32)
    return api_key, api_secret, api_key


async def criar_empresa(
    dados: EmpresaCreateRequest,
    *,
    session: Any,
) -> EmpresaCreateResponse:
    """Cria a Empresa + APIClient (plano free) e retorna as credenciais.

    O par (api_key, api_secret) é exibido uma única vez na resposta.
    """
    async with _session_ctx(session) as db:
        existente = (
            await db.execute(select(Empresa).where(Empresa.cnpj == dados.cnpj))
        ).scalar_one_or_none()
        if existente is not None:
            raise EmpresaJaExiste(f"Já existe empresa com o CNPJ {dados.cnpj}")

        empresa = Empresa(
            cnpj=dados.cnpj,
            razao_social=dados.razao_social,
            nome_fantasia=dados.nome_fantasia,
            inscricao_estadual=dados.inscricao_estadual,
            uf=dados.uf,
            codigo_regime_tributario=dados.codigo_regime_tributario,
            csc=dados.csc,
            csc_id=dados.csc_id,
        )
        db.add(empresa)
        await db.flush()

        api_key, api_secret, prefixo = _gerar_credenciais()
        client = APIClient(
            name=dados.client_name or f"Client {dados.razao_social}",
            api_key_hash=hash_api_key(api_secret),
            api_key_prefix=prefixo,
            plano=PLANO_PADRAO,
            is_active=True,
            empresa_id=empresa.id,
        )
        db.add(client)
        await db.commit()
        await db.refresh(empresa)

        return EmpresaCreateResponse(
            empresa_id=empresa.id,
            cnpj=empresa.cnpj,
            razao_social=empresa.razao_social,
            api_key=api_key,
            api_secret=api_secret,
            api_key_prefix=prefixo,
            csc_id=empresa.csc_id,
            csc_mascarado=mascarar_csc(empresa.csc),
        )


async def atualizar_empresa(
    empresa_id: UUID,
    dados: EmpresaUpdateRequest,
    *,
    session: Any,
) -> EmpresaUpdateResponse:
    """Atualiza campos parciais da empresa (incl. csc/csc_id da NFC-e)."""
    async with _session_ctx(session) as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None:
            raise EmpresaNaoEncontrada(f"Empresa {empresa_id} não encontrada")

        for campo, valor in dados.model_dump(exclude_unset=True).items():
            setattr(empresa, campo, valor)
        await db.commit()
        await db.refresh(empresa)

        return EmpresaUpdateResponse(
            empresa_id=empresa.id,
            cnpj=empresa.cnpj,
            razao_social=empresa.razao_social,
            nome_fantasia=empresa.nome_fantasia,
            inscricao_estadual=empresa.inscricao_estadual,
            uf=empresa.uf,
            csc_id=empresa.csc_id,
            csc_mascarado=mascarar_csc(empresa.csc),
        )
