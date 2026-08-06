"""Testes de integração do status SEFAZ (GET /api/v1/sefaz/status)."""

from __future__ import annotations

import time

from tests.api.conftest import authorization_headers, run

XML_STATUS_OPERACIONAL = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retConsStatServ xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
        <tpAmb>2</tpAmb>
        <verAplic>PR_4.00</verAplic>
        <cStat>107</cStat>
        <xMotivo>Servico em Operacao</xMotivo>
        <cUF>35</cUF>
        <dhRecbto>2026-08-06T12:00:00-03:00</dhRecbto>
        <tMed>1</tMed>
      </retConsStatServ>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""


async def _remover_certificado(db, empresa_id):
    """Remove cert_pem/key_pem da empresa no banco de teste."""
    from sqlalchemy import select

    from api.models import Empresa

    async with db() as session:
        empresa = (
            await session.execute(select(Empresa).where(Empresa.id == empresa_id))
        ).scalar_one()
        empresa.cert_pem = None
        empresa.key_pem = None
        await session.commit()


def test_status_uf_operacional(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """Cenário feliz: SEFAZ responde cStat 107 e o status é operacional."""
    sefaz_mock.xml_resposta = XML_STATUS_OPERACIONAL

    resp = run(client.get("/api/v1/sefaz/status/SP", headers=authorization_headers(auth_token)))

    assert resp.status_code == 200
    data = resp.json()
    assert data["uf"] == "SP"
    assert data["status"] == "operacional"
    assert data["cstat"] == "107"
    assert data["mensagem"] == "Servico em Operacao"
    assert data["ultima_consulta"] == "2026-08-06T12:00:00-03:00"
    assert "tempo_resposta_ms" in data
    assert len(sefaz_mock.chamadas) == 1


def test_status_uf_cache_hit_nao_chama_sefaz(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """Cache KV: a 2ª chamada em <60s não consulta a SEFAZ e é rápida (<20ms)."""
    sefaz_mock.xml_resposta = XML_STATUS_OPERACIONAL
    headers = authorization_headers(auth_token)

    first = run(client.get("/api/v1/sefaz/status/SP", headers=headers))
    assert first.status_code == 200
    assert len(sefaz_mock.chamadas) == 1

    inicio = time.monotonic()
    second = run(client.get("/api/v1/sefaz/status/SP", headers=headers))
    duracao_ms = (time.monotonic() - inicio) * 1000

    assert second.status_code == 200
    assert second.json() == first.json()
    # SEFAZ não foi chamada de novo
    assert len(sefaz_mock.chamadas) == 1
    # Chamada cacheada deve ser rápida
    assert duracao_ms < 20, f"chamada cacheada demorou {duracao_ms:.1f}ms"


def test_status_uf_invalida_retorna_400(client, empresa, api_client, auth_token):
    """UF fora da lista (ex.: XX) retorna 400."""
    resp = run(client.get("/api/v1/sefaz/status/XX", headers=authorization_headers(auth_token)))
    assert resp.status_code == 400


def test_status_todas_ufs(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """GET /sefaz/status retorna as 27 UFs."""
    sefaz_mock.xml_resposta = XML_STATUS_OPERACIONAL

    resp = run(client.get("/api/v1/sefaz/status", headers=authorization_headers(auth_token)))

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 27
    assert {item["uf"] for item in data} == {
        "RO",
        "AC",
        "AM",
        "RR",
        "PA",
        "AP",
        "TO",
        "MA",
        "PI",
        "CE",
        "RN",
        "PB",
        "PE",
        "AL",
        "SE",
        "BA",
        "MG",
        "ES",
        "RJ",
        "SP",
        "PR",
        "SC",
        "RS",
        "MS",
        "MT",
        "GO",
        "DF",
    }
    assert all(item["status"] == "operacional" for item in data)
    assert len(sefaz_mock.chamadas) == 27


def test_status_uf_sem_certificado_retorna_400(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Empresa sem certificado cadastrado retorna 400 na primeira consulta."""
    run(_remover_certificado(db, empresa.id))

    resp = run(client.get("/api/v1/sefaz/status/SP", headers=authorization_headers(auth_token)))

    assert resp.status_code == 400
    assert "certificado" in resp.json()["detail"]
