"""Testes do serviço de certificado digital (Blob + KV + Postgres).

O módulo `api.utils.crypto` lê settings no import, então as env vars são
definidas antes de qualquer import da API. O PFX de teste é gerado em memória
com `cryptography`.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Self
from uuid import uuid4

# --- env vars ANTES dos imports da API -------------------------------------
import pytest
from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["KV_URL"] = "redis://localhost:6379"
os.environ["KV_TOKEN"] = "test"
os.environ["BLOB_READ_WRITE_TOKEN"] = "test-blob-token"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from api.models import Empresa
from api.schemas.empresa import CertificadoUploadResponse
from api.services.certificado_service import (
    BLOB_BASE_URL,
    PEM_CACHE_KEY,
    PEM_CACHE_TTL,
    _cache_pem,
    _extrair_pems,
    _upload_blob,
    _validade_certificado,
    obter_pem,
    upload_certificado,
)
from api.utils.crypto import decrypt_bytes, decrypt_senha

SENHA_PFX = "1234"


def gerar_pfx_bytes(senha: str = SENHA_PFX) -> bytes:
    """Gera um certificado A1 self-signed em formato PFX (memória)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Teste LTDA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Teste LTDA"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return serialization.pkcs12.serialize_key_and_certificates(
        b"teste",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(senha.encode()),
    )


PFX_BYTES = gerar_pfx_bytes()


class FakeRedis:
    """Redis em memória com get/set (para o cache KV)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex


class FakeSession:
    """Sessão async fake com uma Empresa em memória."""

    def __init__(self, empresa: Empresa | None) -> None:
        self.empresa = empresa
        self.commit_called = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, model, pk):
        return self.empresa

    async def commit(self) -> None:
        self.commit_called = True


class FakeHttpClient:
    """Cliente HTTP fake para o Vercel Blob."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.put_calls: list[tuple] = []

    async def put(self, url, content=None, headers=None):
        self.put_calls.append((url, content, headers))
        return _FakeResponse({"url": self.url, "pathname": "x.pfx"})

    async def aclose(self) -> None:
        return None


class _FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


def run(coro) -> object:
    """Roda coroutine sem depender de pytest-asyncio."""
    return asyncio.run(coro)


def empresa_fake() -> Empresa:
    empresa = Empresa(cnpj="99999999000199", razao_social="Empresa Teste LTDA")
    empresa.id = uuid4()
    return empresa


# ---------------------------------------------------------------------------
# Extração de PEMs
# ---------------------------------------------------------------------------


def test_extrair_pems_pfx_valido():
    key_pem, cert_pem = _extrair_pems(PFX_BYTES, SENHA_PFX)
    assert "BEGIN PRIVATE KEY" in key_pem
    assert "BEGIN CERTIFICATE" in cert_pem


def test_extrair_pems_senha_invalida():
    with pytest.raises(Exception, match="senha"):
        _extrair_pems(PFX_BYTES, "senha-errada")


def test_validade_certificado():
    _, cert_pem = _extrair_pems(PFX_BYTES, SENHA_PFX)
    validade = _validade_certificado(cert_pem)
    assert validade is not None
    assert validade > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Blob
# ---------------------------------------------------------------------------


def test_upload_blob_envia_put_e_retorna_url():
    http = FakeHttpClient("https://blob.vercel-storage.com/certificados/x.pfx")
    url = run(_upload_blob(b"pfx-cifrado", "certificados/x.pfx", http_client=http, token="t"))

    assert url == http.url
    assert len(http.put_calls) == 1
    put_url, content, headers = http.put_calls[0]
    assert put_url == f"{BLOB_BASE_URL}/certificados/x.pfx"
    assert content == b"pfx-cifrado"
    assert headers["Authorization"] == "Bearer t"


# ---------------------------------------------------------------------------
# Cache KV
# ---------------------------------------------------------------------------


def test_cache_pem_ttl_1h():
    redis = FakeRedis()
    run(_cache_pem(redis, uuid4(), "KEY", "CERT"))
    key = next(iter(redis.store))
    assert redis.ttls[key] == PEM_CACHE_TTL
    data = json.loads(redis.store[key])
    assert data == {"cert_pem": "CERT", "key_pem": "KEY"}


# ---------------------------------------------------------------------------
# Upload completo (3 camadas)
# ---------------------------------------------------------------------------


def test_upload_certificado_fluxo_completo():
    empresa = empresa_fake()
    redis = FakeRedis()
    session = FakeSession(empresa)
    http = FakeHttpClient("https://blob.vercel-storage.com/certificados/x.pfx")

    resp = run(
        upload_certificado(
            empresa.id,
            PFX_BYTES,
            SENHA_PFX,
            redis=redis,
            session=session,
            http_client=http,
        )
    )

    assert isinstance(resp, CertificadoUploadResponse)
    assert resp.empresa_id == empresa.id
    assert resp.cnpj == "99999999000199"
    assert resp.razao_social == "Empresa Teste LTDA"
    assert resp.certificado_nome_arquivo == f"certificados/{empresa.id}.pfx"
    assert resp.validade is not None

    # Postgres (metadados persistidos)
    assert session.commit_called is True
    assert "BEGIN CERTIFICATE" in empresa.cert_pem
    assert "BEGIN PRIVATE KEY" in empresa.key_pem
    assert empresa.certificado_blob_url == http.url
    # Senha guardada criptografada (Fernet) e recuperável
    assert empresa.certificado_senha != SENHA_PFX
    assert decrypt_senha(empresa.certificado_senha) == SENHA_PFX

    # KV (cache populado com TTL)
    key = PEM_CACHE_KEY.format(empresa_id=empresa.id)
    assert key in redis.store
    assert redis.ttls[key] == PEM_CACHE_TTL
    data = json.loads(redis.store[key])
    assert data["cert_pem"] == empresa.cert_pem
    assert data["key_pem"] == empresa.key_pem


def test_upload_certificado_pfx_cifrado_no_blob():
    empresa = empresa_fake()
    redis = FakeRedis()
    session = FakeSession(empresa)
    http = FakeHttpClient("https://blob.vercel-storage.com/x.pfx")

    run(
        upload_certificado(
            empresa.id,
            PFX_BYTES,
            SENHA_PFX,
            redis=redis,
            session=session,
            http_client=http,
        )
    )

    # O conteúdo enviado ao blob é o PFX criptografado (Fernet), não o PFX cru
    content = http.put_calls[0][1]
    pfx_recuperado = decrypt_bytes(content.decode())
    assert pfx_recuperado == PFX_BYTES


def test_upload_certificado_empresa_nao_encontrada():
    redis = FakeRedis()
    session = FakeSession(None)  # empresa não existe
    http = FakeHttpClient("https://blob.vercel-storage.com/x.pfx")

    try:
        run(
            upload_certificado(
                uuid4(),
                PFX_BYTES,
                SENHA_PFX,
                redis=redis,
                session=session,
                http_client=http,
            )
        )
    except ValueError as exc:
        assert "não encontrada" in str(exc)
    else:
        raise AssertionError("empresa ausente deveria levantar ValueError")


# ---------------------------------------------------------------------------
# Leitura (KV primeiro, Postgres fallback)
# ---------------------------------------------------------------------------


def test_obter_pem_cache_hit():
    empresa = empresa_fake()
    redis = FakeRedis()
    run(_cache_pem(redis, empresa.id, "KEY", "CERT"))

    cert, key = run(obter_pem(empresa.id, redis=redis, session=FakeSession(empresa)))
    assert (cert, key) == ("CERT", "KEY")


def test_obter_pem_cache_miss_lê_postgres_e_popula_cache():
    empresa = empresa_fake()
    empresa.cert_pem = "CERT-DB"
    empresa.key_pem = "KEY-DB"
    redis = FakeRedis()

    cert, key = run(obter_pem(empresa.id, redis=redis, session=FakeSession(empresa)))
    assert (cert, key) == ("CERT-DB", "KEY-DB")
    key_cache = PEM_CACHE_KEY.format(empresa_id=empresa.id)
    assert key_cache in redis.store  # cache repopulado


def test_obter_pem_sem_certificado():
    empresa = empresa_fake()  # sem cert_pem/key_pem
    redis = FakeRedis()
    assert run(obter_pem(empresa.id, redis=redis, session=FakeSession(empresa))) is None
