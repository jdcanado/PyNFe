"""Fixtures de integração da API.

- Banco: SQLite assíncrono em memória (aiosqlite + StaticPool), com as
  tabelas criadas via `Base.metadata.create_all`.
- Redis: fake em memória (substitui o cliente Upstash).
- SEFAZ: mock do `requests.post` usado pelo `ComunicacaoSefaz`.
- Cliente HTTP: httpx AsyncClient com ASGITransport (sem servidor real).

As env vars são definidas antes de qualquer import da API porque módulos
como `api.core.config` e `api.utils.crypto` leem settings no import.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

# --- env vars ANTES dos imports da API -------------------------------------
from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["KV_URL"] = "redis://localhost:6379"
os.environ["KV_TOKEN"] = "test"
os.environ["BLOB_READ_WRITE_TOKEN"] = "test-blob-token"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from api.core.security import hash_api_key
from api.main import create_app
from api.models import APIClient, Empresa
from api.models.base import Base

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


def extrair_pems() -> tuple[str, str]:
    """Extrai (key_pem, cert_pem) do PFX de teste."""
    from pynfe.entidades.certificado import CertificadoA1

    key_pem, cert_pem = CertificadoA1(pfx_bytes=gerar_pfx_bytes()).separar_arquivo(SENHA_PFX)
    return key_pem.decode(), cert_pem


def run(coro) -> Any:
    """Roda coroutine sem depender de pytest-asyncio."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Banco (SQLite em memória)
# ---------------------------------------------------------------------------


@pytest.fixture
def db(monkeypatch):
    """Engine SQLite em memória com as tabelas criadas; substitui SessionFactory."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    run(_init())
    monkeypatch.setattr("api.core.database.SessionFactory", factory)
    yield factory
    run(engine.dispose())


# ---------------------------------------------------------------------------
# Redis fake
# ---------------------------------------------------------------------------


class FakePipeline:
    """Pipeline Redis em memória que executa os comandos na ordem."""

    def __init__(self, store: dict) -> None:
        self._store = store
        self._commands: list[tuple] = []

    def zremrangebyscore(self, key: str, min_: float, max_: float) -> FakePipeline:
        self._commands.append(("zremrangebyscore", key, min_, max_))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> FakePipeline:
        self._commands.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> FakePipeline:
        self._commands.append(("zcard", key))
        return self

    def expire(self, key: str, ttl: int) -> FakePipeline:
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results: list = []
        for command, *args in self._commands:
            if command == "zremrangebyscore":
                key, min_, max_ = args
                self._store[key] = {
                    member: score
                    for member, score in self._store.get(key, {}).items()
                    if not (min_ <= score <= max_)
                }
                results.append(None)
            elif command == "zadd":
                key, mapping = args
                self._store.setdefault(key, {}).update(mapping)
                results.append(len(mapping))
            elif command == "zcard":
                key = args[0]
                results.append(len(self._store.get(key, {})))
            elif command == "expire":
                results.append(True)
        return results


class FakeRedis:
    """Redis em memória com get/set (cache PEM) e pipeline (rate limit)."""

    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store)


@pytest.fixture(autouse=True)
def redis_fake(monkeypatch):
    """Substitui o cliente Redis (Upstash) por um fake em memória."""
    fake = FakeRedis()
    monkeypatch.setattr("api.core.dependencies.get_redis", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# Mock SEFAZ (requests.post usado pelo ComunicacaoSefaz)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode()


class FakeRequests:
    """Substitui o módulo `requests` do comunicacao; post() devolve o XML mock."""

    def __init__(self) -> None:
        self.xml_resposta: str = XML_SEFAZ_AUTORIZADA
        self.chamadas: list[tuple] = []

    def post(self, url, data=None, headers=None, cert=None, verify=False, timeout=None):
        self.chamadas.append((url, data, headers))
        return FakeResponse(self.xml_resposta)


XML_SEFAZ_AUTORIZADA = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retEnviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
        <cStat>104</cStat>
        <xMotivo>Lote processado</xMotivo>
        <protNFe>
          <infProt>
            <cStat>100</cStat>
            <xMotivo>Autorizado o uso da NF-e</xMotivo>
            <nProt>351111111111111</nProt>
          </infProt>
        </protNFe>
      </retEnviNFe>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""


@pytest.fixture
def sefaz_mock(monkeypatch):
    """Mock da comunicação SEFAZ (requests.post). Permite trocar a resposta."""
    fake = FakeRequests()
    monkeypatch.setattr("pynfe.processamento.comunicacao.requests", fake)
    return fake


# ---------------------------------------------------------------------------
# App e cliente HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    """Cliente HTTP assíncrono sobre o app via ASGITransport."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Dados: empresa com certificado e API client
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    """Empresa com certificado (PEM) cadastrado no banco de teste."""
    key_pem, cert_pem = extrair_pems()

    async def _criar() -> Empresa:
        async with db() as session:
            empresa = Empresa(
                cnpj="99999999000199",
                razao_social="Empresa Teste LTDA",
                uf="PR",
                cert_pem=cert_pem,
                key_pem=key_pem,
            )
            session.add(empresa)
            await session.commit()
            await session.refresh(empresa)
            return empresa

    return run(_criar())


@pytest.fixture
def api_client(db, empresa) -> APIClient:
    """API client ativo vinculado à empresa (para testes de auth)."""
    api_secret = "segredo-da-chave"

    async def _criar() -> APIClient:
        async with db() as session:
            client = APIClient(
                name="Cliente Teste",
                api_key_hash=hash_api_key(api_secret),
                api_key_prefix="teste01",
                is_active=True,
                empresa_id=empresa.id,
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            return client

    return run(_criar())


@pytest.fixture
def auth_token(api_client) -> str:
    """JWT válido do API client de teste (header Authorization: Bearer)."""
    from api.core.security import create_jwt_token

    return create_jwt_token(str(api_client.id), {"client": api_client.name})


def authorization_headers(auth_token: str) -> dict:
    """Headers com o token de autenticação."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def payload_nfe(empresa) -> dict:
    """Payload JSON válido de emissão de NF-e."""
    return {
        "empresa_id": str(empresa.id),
        "uf": "PR",
        "municipio": "4118402",
        "natureza_operacao": "VENDA",
        "tipo_documento": 1,
        "data_emissao": "2026-08-05T12:00:00Z",
        "modelo": 55,
        "serie": "1",
        "numero": "111",
        "forma_emissao": "1",
        "finalidade_emissao": "1",
        "emitente": {
            "razao_social": "Empresa Teste LTDA",
            "cnpj": "99999999000199",
            "inscricao_estadual": "9999999999",
            "codigo_de_regime_tributario": "3",
            "endereco_logradouro": "Rua da Paz",
            "endereco_numero": "666",
            "endereco_bairro": "Sossego",
            "endereco_uf": "PR",
            "endereco_municipio": "Paranavaí",
            "endereco_cod_municipio": "4118402",
            "endereco_cep": "87704000",
        },
        "cliente": {
            "razao_social": "JOSE DA SILVA",
            "tipo_documento": "CPF",
            "numero_documento": "12345678900",
            "indicador_ie": 9,
            "endereco_logradouro": "Rua dos Bobos",
            "endereco_numero": "Zero",
            "endereco_bairro": "Aquele Mesmo",
            "endereco_uf": "DF",
            "endereco_municipio": "Brasilia",
            "endereco_cep": "12345123",
        },
        "produtos": [
            {
                "codigo": "000328",
                "descricao": "Produto teste",
                "ncm": "99999999",
                "cfop": "5102",
                "ean": "1234567890121",
                "unidade_comercial": "UN",
                "quantidade_comercial": "12",
                "valor_unitario_comercial": "9.75",
                "valor_total_bruto": "117.00",
                "icms": {
                    "modalidade": "00",
                    "origem": 0,
                    "valor_base_calculo": "117.00",
                    "aliquota": "18.00",
                    "valor": "21.06",
                },
                "pis": {
                    "situacao_tributaria": "01",
                    "valor_base_calculo": "117.00",
                    "aliquota_percentual": "0.65",
                    "valor": "0.76",
                },
                "cofins": {
                    "situacao_tributaria": "01",
                    "valor_base_calculo": "117.00",
                    "aliquota_percentual": "3.00",
                    "valor": "3.51",
                },
            }
        ],
        "pagamentos": [{"forma_pagamento": "01", "valor": "117.00"}],
    }


@pytest.fixture(autouse=True)
def limpar_fonte_dados():
    """Limpa a fonte de dados global do PyNFe entre testes."""
    from pynfe.entidades.fonte_dados import _fonte_dados

    _fonte_dados.limpar_dados()
    yield
    _fonte_dados.limpar_dados()
