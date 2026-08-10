"""Testes de integração da consulta de GTIN (GET/POST /api/v1/gtin)."""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run

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


def test_consultar_gtin_individual(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """GET /gtin/consultar/{codigo} retorna os dados do GTIN."""
    sefaz_mock.xml_resposta = XML_GTIN_ENCONTRADO

    resp = run(
        client.get(
            "/api/v1/gtin/consultar/7891234567890",
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["codigo_gtin"] == "7891234567890"
    assert data["encontrado"] is True
    assert data["descricao"] == "Produto Teste"
    assert data["ncm"] == "22030000"


def test_consultar_gtin_lote_50(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """POST /gtin/consultar/lote com 50 códigos retorna 50 resultados."""
    sefaz_mock.xml_resposta = XML_GTIN_ENCONTRADO
    codigos = [f"789{i:010d}" for i in range(50)]

    resp = run(
        client.post(
            "/api/v1/gtin/consultar/lote",
            json={"codigos": codigos},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["consultados"] == 50
    assert data["encontrados"] == 50
    assert len(data["resultados"]) == 50


def test_consultar_gtin_sem_token_retorna_401(client):
    """Rota protegida sem token retorna 401."""
    resp = run(client.get("/api/v1/gtin/consultar/7891234567890"))
    assert resp.status_code == 401


def test_consultar_gtin_envia_soapaction_do_svrs(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """A requisicao ao SVRS leva SOAPAction e Content-Type com action."""
    sefaz_mock.xml_resposta = XML_GTIN_ENCONTRADO

    resp = run(
        client.get(
            "/api/v1/gtin/consultar/7891234567890",
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    assert len(sefaz_mock.chamadas) == 1
    _url, _data, headers = sefaz_mock.chamadas[0]
    soap_action = "http://www.portalfiscal.inf.br/nfe/wsdl/ccgConsGtin/ccgConsGTIN"
    assert headers["SOAPAction"] == soap_action
    assert f'action="{soap_action}"' in headers["content-type"]
