"""Serviço de certificado digital A1 — estratégia de 3 camadas.

1. **Blob (Vercel Blob)**: PFX original criptografado com Fernet (recuperável).
2. **KV (Upstash Redis)**: PEM (cert/key) em cache com TTL de 1 hora.
3. **Postgres**: metadados (cert_pem, key_pem, senha Fernet, URL do blob).

Dependências (Redis, sessão, HTTP) são injetáveis para permitir testes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from cryptography import x509

from api.core.config import get_settings
from api.core.exceptions import EmpresaNaoEncontrada
from api.models import Empresa
from api.schemas.empresa import CertificadoUploadResponse
from api.utils.crypto import encrypt_bytes, encrypt_senha
from pynfe.entidades.certificado import CertificadoA1

BLOB_BASE_URL = "https://blob.vercel-storage.com"
PEM_CACHE_TTL = 3_600  # 1 hora

from api.core.logging import get_logger

PEM_CACHE_KEY = "cert:pem:{empresa_id}"

logger = get_logger("api.certificado_service")


@asynccontextmanager
async def _session_ctx(session: Any):
    """Abre uma AsyncSession (ou sessão fake de teste) como contexto."""
    async with session as db:
        yield db


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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao extrair validade do certificado: %s", exc)
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
    settings = get_settings()
    token = token if token is not None else settings.blob_read_write_token
    store_id = settings.blob_store_id
    url = f"{BLOB_BASE_URL}/{nome_arquivo}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    if store_id:
        headers["x-store-id"] = store_id
    headers["x-vercel-blob-access"] = "private"

    client = http_client or httpx.AsyncClient()
    try:
        resp = await client.put(url, content=dados, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "Blob upload falhou: status=%s body=%s headers_sent=%s",
                resp.status_code,
                resp.text,
                {k: v for k, v in headers.items()},
            )
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
    redis: Any,
    session: Any,
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

    async with _session_ctx(session) as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None:
            raise EmpresaNaoEncontrada(f"Empresa {empresa_id} não encontrada")
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
    redis: Any,
    session: Any,
) -> tuple[str, str] | None:
    """Retorna (cert_pem, key_pem) da empresa.

    Busca primeiro no cache KV (TTL 1h); se ausente, lê do Postgres e
    repopula o cache. Retorna None se a empresa não tem certificado.
    """
    key = PEM_CACHE_KEY.format(empresa_id=empresa_id)

    cached = await redis.get(key)
    if cached:
        data = json.loads(cached)
        return data["cert_pem"], data["key_pem"]

    async with _session_ctx(session) as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None or not empresa.cert_pem or not empresa.key_pem:
            return None
        cert_pem, key_pem = empresa.cert_pem, empresa.key_pem

    await _cache_pem(redis, empresa_id, key_pem, cert_pem)
    return cert_pem, key_pem
