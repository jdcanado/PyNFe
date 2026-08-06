"""Serviço de certificado digital A1 — estratégia de 3 camadas.

1. **Blob (Vercel Blob)**: PFX original criptografado com Fernet (recuperável).
2. **KV (Upstash Redis)**: PEM (cert/key) em cache com TTL de 1 hora.
3. **Postgres**: metadados (cert_pem, key_pem, senha Fernet, URL do blob).

Dependências (Redis, sessão, HTTP) são injetáveis para permitir testes.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from cryptography import x509

from api.models import Empresa
from api.schemas.empresa import CertificadoUploadResponse
from api.utils.crypto import encrypt_bytes, encrypt_senha
from pynfe.entidades.certificado import CertificadoA1

BLOB_BASE_URL = "https://blob.vercel-storage.com"
PEM_CACHE_TTL = 3_600  # 1 hora

PEM_CACHE_KEY = "cert:pem:{empresa_id}"


def _get_settings():
    """Import lazy de settings (evita exigir env vars no import do módulo)."""
    from api.core.config import get_settings

    return get_settings()


def _get_redis():
    """Import lazy do cliente Redis singleton."""
    from api.core.dependencies import get_redis

    return get_redis()


def _get_session_factory():
    """Import lazy do factory de sessão async."""
    from api.core.database import SessionFactory

    return SessionFactory


# ---------------------------------------------------------------------------
# Extração de PEMs
# ---------------------------------------------------------------------------


def _extrair_pems(pfx_bytes: bytes, senha: str) -> tuple[str, str]:
    """Extrai (key_pem, cert_pem) do PFX usando a entidade CertificadoA1."""
    key_pem, cert_pem = CertificadoA1(pfx_bytes=pfx_bytes).separar_arquivo(senha)
    if isinstance(key_pem, bytes):
        key_pem = key_pem.decode("utf-8")
    if isinstance(cert_pem, bytes):
        cert_pem = cert_pem.decode("utf-8")
    return key_pem, cert_pem


def _validade_certificado(cert_pem: str) -> datetime | None:
    """Extrai a data de validade (not_valid_after) do certificado PEM."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        # `not_valid_after_utc` retorna aware; fallback para versões antigas
        try:
            return cert.not_valid_after_utc
        except AttributeError:
            return cert.not_valid_after
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Camadas: Blob e KV
# ---------------------------------------------------------------------------


async def _upload_blob(
    dados: bytes,
    nome_arquivo: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    token: str | None = None,
) -> str:
    """Envia `dados` ao Vercel Blob via PUT e retorna a URL pública."""
    token = token if token is not None else _get_settings().blob_read_write_token
    url = f"{BLOB_BASE_URL}/{nome_arquivo}"
    headers = {"Authorization": f"Bearer {token}"}

    client = http_client or httpx.AsyncClient()
    try:
        resp = await client.put(url, content=dados, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["url"]
    finally:
        if http_client is None:
            await client.aclose()


async def _cache_pem(redis: Any, empresa_id: UUID, key_pem: str, cert_pem: str) -> None:
    """Grava os PEMs no KV com TTL de 1 hora."""
    payload = json.dumps({"cert_pem": cert_pem, "key_pem": key_pem})
    await redis.set(PEM_CACHE_KEY.format(empresa_id=empresa_id), payload, ex=PEM_CACHE_TTL)


# ---------------------------------------------------------------------------
# Upload (escrita nas 3 camadas)
# ---------------------------------------------------------------------------


async def upload_certificado(
    empresa_id: UUID,
    pfx_bytes: bytes,
    senha: str,
    *,
    redis: Any | None = None,
    session: Any | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CertificadoUploadResponse:
    """Processa o upload do PFX nas 3 camadas e retorna a resposta.

    - Valida o PFX e extrai key_pem/cert_pem (levanta se senha inválida).
    - Envia o PFX criptografado (Fernet) para o Vercel Blob.
    - Persiste metadados no Postgres (PEMs + senha Fernet + URL do blob).
    - Popula o cache KV com TTL de 1 hora.
    """
    key_pem, cert_pem = _extrair_pems(pfx_bytes, senha)
    validade = _validade_certificado(cert_pem)

    nome_arquivo = f"certificados/{empresa_id}.pfx"
    pfx_cifrado = encrypt_bytes(pfx_bytes).encode()
    blob_url = await _upload_blob(pfx_cifrado, nome_arquivo, http_client=http_client)

    redis = redis or _get_redis()
    session = session if session is not None else _get_session_factory()

    async with session as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None:
            raise ValueError(f"Empresa {empresa_id} não encontrada")
        empresa.cert_pem = cert_pem
        empresa.key_pem = key_pem
        empresa.certificado_senha = encrypt_senha(senha)
        empresa.certificado_blob_url = blob_url
        await db.commit()
        cnpj = empresa.cnpj
        razao_social = empresa.razao_social

    await _cache_pem(redis, empresa_id, key_pem, cert_pem)

    return CertificadoUploadResponse(
        empresa_id=empresa_id,
        cnpj=cnpj,
        razao_social=razao_social,
        certificado_nome_arquivo=nome_arquivo,
        validade=validade,
    )


# ---------------------------------------------------------------------------
# Leitura (KV primeiro, Postgres como fallback)
# ---------------------------------------------------------------------------


async def obter_pem(
    empresa_id: UUID,
    *,
    redis: Any | None = None,
    session: Any | None = None,
) -> tuple[str, str] | None:
    """Retorna (cert_pem, key_pem) da empresa.

    Busca primeiro no cache KV (TTL 1h); se ausente, lê do Postgres e
    repopula o cache. Retorna None se a empresa não tem certificado.
    """
    redis = redis or _get_redis()
    key = PEM_CACHE_KEY.format(empresa_id=empresa_id)

    cached = await redis.get(key)
    if cached:
        data = json.loads(cached)
        return data["cert_pem"], data["key_pem"]

    session = session if session is not None else _get_session_factory()
    async with session as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None or not empresa.cert_pem or not empresa.key_pem:
            return None
        cert_pem, key_pem = empresa.cert_pem, empresa.key_pem

    await _cache_pem(redis, empresa_id, key_pem, cert_pem)
    return cert_pem, key_pem
