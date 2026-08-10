"""Testes do serviço de consulta de GTIN (cache KV + SEFAZ SP)."""

from __future__ import annotations

import asyncio
import os

# --- env vars ANTES dos imports da API -------------------------------------
from cryptography.fernet import Fernet
from typing_extensions import Self

os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["KV_URL"] = "redis://localhost:6379"
os.environ["KV_TOKEN"] = "test"
os.environ["BLOB_READ_WRITE_TOKEN"] = "test-blob-token"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

from api.services.gtin_service import (
    GTIN_CACHE_KEY,
    GTIN_CACHE_TTL,
    consultar_individual,
    consultar_lote,
)

XML_GTIN_ENCONTRADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <retConsGTIN xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
      <verAplic>SVRS20250801</verAplic>
      <cStat>138</cStat>
      <xMotivo>GTIN consultado com sucesso</xMotivo>
      <dhResp>2026-08-10T12:00:00-03:00</dhResp>
      <GTIN>7891234567890</GTIN>
      <tpGTIN>GTIN-13</tpGTIN>
      <xProd>Produto Teste</xProd>
      <NCM>22030000</NCM>
      <CEST>0300100</CEST>
    </retConsGTIN>
  </soap:Body>
</soap:Envelope>
"""

XML_GTIN_NAO_ENCONTRADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <retConsGTIN xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
      <verAplic>SVRS20250801</verAplic>
      <cStat>139</cStat>
      <xMotivo>GTIN nao localizado</xMotivo>
      <dhResp>2026-08-10T12:00:00-03:00</dhResp>
    </retConsGTIN>
  </soap:Body>
</soap:Envelope>
"""


class FakeRetorno:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex


class FakeSession:
    def __init__(self) -> None:
        self.adicionados: list = []
        self.commit_called = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    def add(self, obj) -> None:
        self.adicionados.append(obj)

    async def commit(self) -> None:
        self.commit_called = True


def run(coro) -> object:
    return asyncio.run(coro)


def mockar_sefaz(
    monkeypatch, xml_resposta: str = XML_GTIN_ENCONTRADO, chamadas: list | None = None
):
    """Substitui o consulta_gtin do ComunicacaoSefaz por um mock."""

    def fake_consulta_gtin(self, gtin, timeout=None):
        if chamadas is not None:
            chamadas.append(gtin)
        return FakeRetorno(xml_resposta)

    monkeypatch.setattr(
        "pynfe.processamento.comunicacao.ComunicacaoSefaz.consulta_gtin", fake_consulta_gtin
    )


def test_consultar_individual_retorna_dados(monkeypatch):
    chamadas: list = []
    mockar_sefaz(monkeypatch, chamadas=chamadas)
    redis = FakeRedis()
    session = FakeSession()

    resultado = run(consultar_individual(session, redis, "7891234567890"))

    assert resultado["codigo_gtin"] == "7891234567890"
    assert resultado["encontrado"] is True
    assert resultado["descricao"] == "Produto Teste"
    assert resultado["marca"] is None  # leiaute v1.00 nao fornece
    assert resultado["ncm"] == "22030000"
    assert resultado["cest"] == "0300100"
    assert resultado["gpc"] is None  # leiaute v1.00 nao fornece
    assert len(chamadas) == 1

    # Cache salvo com TTL de 24h e consulta registrada no banco
    key = GTIN_CACHE_KEY.format(codigo="7891234567890")
    assert redis.ttls[key] == GTIN_CACHE_TTL
    assert session.commit_called is True
    assert len(session.adicionados) == 1


def test_cache_evita_segunda_consulta_sefaz(monkeypatch):
    chamadas: list = []
    mockar_sefaz(monkeypatch, chamadas=chamadas)
    redis = FakeRedis()
    session = FakeSession()

    run(consultar_individual(session, redis, "7891234567890"))
    run(consultar_individual(session, redis, "7891234567890"))

    assert len(chamadas) == 1  # 2ª chamada veio do cache KV


def test_cache_expira_com_ttl_zero(monkeypatch):
    chamadas: list = []
    mockar_sefaz(monkeypatch, chamadas=chamadas)
    redis = FakeRedis()
    session = FakeSession()

    run(consultar_individual(session, redis, "7891234567890", ttl=0))
    run(consultar_individual(session, redis, "7891234567890", ttl=0))

    assert len(chamadas) == 2  # sem cache (TTL 0 = expiração imediata)


def test_consultar_lote_retorna_lista(monkeypatch):
    chamadas: list = []
    mockar_sefaz(monkeypatch, chamadas=chamadas)
    redis = FakeRedis()
    session = FakeSession()

    resultados = run(consultar_lote(session, redis, ["7891234567890", "7891234567891"]))

    assert len(resultados) == 2
    assert all(r["encontrado"] for r in resultados)
    assert len(chamadas) == 2


def test_gtin_nao_encontrado(monkeypatch):
    mockar_sefaz(monkeypatch, xml_resposta=XML_GTIN_NAO_ENCONTRADO)
    redis = FakeRedis()
    session = FakeSession()

    resultado = run(consultar_individual(session, redis, "7891234567890"))

    assert resultado["encontrado"] is False
    assert resultado["descricao"] is None
