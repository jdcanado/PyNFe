"""Testes de integração dos novos endpoints de consulta SEFAZ e evento 110112.

Cobre:
- POST /api/v1/nfe/consultar (NFeConsultaProtocolo4 — consulta de situação)
- POST /api/v1/nfe/distribuicao (NFeDistribuicaoDFe — distribuição de DF-e)
- GET /api/v1/nfe/cadastro (CadConsultaCadastro4 — consulta de cadastro)
- POST /api/v1/nfe/operacao-nao-realizada (evento 110112)
"""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run

CHAVE = "35111111111111111111111111111111111111111111"
JUSTIFICATIVA = "Operação não realizada pelo destinatário"

XML_CONSULTA_AUTORIZADA = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retConsSitNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
        <tpAmb>2</tpAmb>
        <verAplic>PR_4.01</verAplic>
        <cStat>100</cStat>
        <xMotivo>Autorizado o uso da NF-e</xMotivo>
        <cUF>41</cUF>
        <dhRecbto>2026-08-10T10:00:00-03:00</dhRecbto>
        <chNFe>35111111111111111111111111111111111111111111</chNFe>
        <protNFe versao="4.00">
          <infProt>
            <chNFe>35111111111111111111111111111111111111111111</chNFe>
            <dhRecbto>2026-08-10T09:00:00-03:00</dhRecbto>
            <nProt>135260000000001</nProt>
            <digVal>abc</digVal>
            <cStat>100</cStat>
            <xMotivo>Autorizado o uso da NF-e</xMotivo>
          </infProt>
        </protNFe>
      </retConsSitNFe>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""

XML_DISTRIBUICAO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
        <tpAmb>2</tpAmb>
        <verAplic>RS_1.0</verAplic>
        <cStat>138</cStat>
        <xMotivo>Documento localizado</xMotivo>
        <dhResp>2026-08-10T10:00:00-03:00</dhResp>
        <ultNSU>000000000000015</ultNSU>
        <maxNSU>000000000000015</maxNSU>
        <loteDistDFeInt>
          <docZip NSU="000000000000015" schema="procNFe_v4.00">SGVsbG8gREYtZSE=</docZip>
        </loteDistDFeInt>
      </retDistDFeInt>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""

XML_CADASTRO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retConsCad xmlns="http://www.portalfiscal.inf.br/nfe" versao="2.00">
        <infCons>
          <verAplic>PR_2.0</verAplic>
          <cStat>111</cStat>
          <xMotivo>Consulta cadastro com uma ocorrencia</xMotivo>
          <UF>PR</UF>
          <CNPJ>99999999000199</CNPJ>
        </infCons>
        <infCad>
          <IE>9999999999</IE>
          <CNPJ>99999999000199</CNPJ>
          <UF>PR</UF>
          <cSit>2</cSit>
          <indCredNFe>1</indCredNFe>
          <indCredCTe>1</indCredCTe>
          <xNome>Empresa Teste LTDA</xNome>
          <ender>
            <xLgr>Rua da Paz</xLgr>
            <nro>666</nro>
            <xBairro>Sossego</xBairro>
            <cMun>4118402</cMun>
            <xMun>Paranavaí</xMun>
            <CEP>87704000</CEP>
          </ender>
        </infCad>
      </retConsCad>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""

XML_EVENTO_REGISTRADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
        <idLote>1</idLote>
        <tpEvento>110112</tpEvento>
        <retEvento versao="1.00">
          <infEvento>
            <tpAmb>2</tpAmb>
            <cOrgao>41</cOrgao>
            <chNFe>35111111111111111111111111111111111111111111</chNFe>
            <cStat>135</cStat>
            <xMotivo>Evento registrado e vinculado a NF-e</xMotivo>
            <nProt>135260000000001</nProt>
          </infEvento>
        </retEvento>
      </retEnvEvento>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""


async def _criar_nota(db, *, empresa_id, chave=CHAVE, modelo="55", status="AUTORIZADA"):
    """Insere uma nota diretamente no banco (evita depender da emissão)."""
    from api.models import NotaFiscal

    async with db() as session:
        nota = NotaFiscal(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=111,
            serie=1,
            modelo=modelo,
            status=status,
            protocolo="351111111111111",
            valor_total=117.0,
        )
        session.add(nota)
        await session.commit()
        await session.refresh(nota)
        return nota


async def _ler_nota(db, chave=CHAVE):
    """Lê status e eventos da nota após a operação."""
    from sqlalchemy import select

    from api.models import NotaFiscal

    async with db() as session:
        nota = (
            await session.execute(select(NotaFiscal).where(NotaFiscal.chave_acesso == chave))
        ).scalar_one()
        return nota.status, nota.eventos


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


# ---------------------------------------------------------------------------
# Consulta de situação (NFeConsultaProtocolo4)
# ---------------------------------------------------------------------------


def test_consultar_nota_sefaz_autorizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """Consulta de situação retorna status autorizada com protocolo."""
    sefaz_mock.xml_resposta = XML_CONSULTA_AUTORIZADA

    resp = run(
        client.post(
            "/api/v1/nfe/consultar",
            json={"chave_acesso": CHAVE},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "autorizada"
    assert data["cstat"] == "100"
    assert data["xmotivo"] == "Autorizado o uso da NF-e"
    assert data["protocolo"] == "135260000000001"
    assert data["modelo"] == "55"
    assert data["ambiente"] == "2"
    assert len(sefaz_mock.chamadas) == 1


def test_consultar_nota_sefaz_sem_certificado_retorna_400(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Empresa sem certificado cadastrado retorna 400."""
    run(_remover_certificado(db, empresa.id))

    resp = run(
        client.post(
            "/api/v1/nfe/consultar",
            json={"chave_acesso": CHAVE},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 400
    assert "certificado" in resp.json()["detail"]
    assert len(sefaz_mock.chamadas) == 0


def test_consultar_nota_chave_invalida_retorna_422(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """Chave com menos de 44 dígitos é rejeitada pela validação (422)."""
    resp = run(
        client.post(
            "/api/v1/nfe/consultar",
            json={"chave_acesso": "123"},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 422
    assert len(sefaz_mock.chamadas) == 0


# ---------------------------------------------------------------------------
# Distribuição de DF-e (NFeDistribuicaoDFe)
# ---------------------------------------------------------------------------


def test_distribuicao_distnsu(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """distNSU: sem chave e sem NSU específico; retorna docZip listados."""
    sefaz_mock.xml_resposta = XML_DISTRIBUICAO

    resp = run(
        client.post(
            "/api/v1/nfe/distribuicao",
            json={"cnpj": "99999999000199", "nsu": 0},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tipo"] == "distNSU"
    assert data["cstat"] == "138"
    assert data["ult_nsu"] == "000000000000015"
    assert data["max_nsu"] == "000000000000015"
    assert data["documentos"] and data["documentos"][0]["nsu"] == "000000000000015"
    assert data["documentos"][0]["schema"] == "procNFe_v4.00"

    # O XML enviado à SEFAZ contém CNPJ do interessado e distNSU
    xml_enviado = sefaz_mock.chamadas[0][1]
    assert "<CNPJ>99999999000199</CNPJ>" in xml_enviado
    assert "<distNSU>" in xml_enviado


def test_distribuicao_conschnfe(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """consChNFe: chave presente define o tipo de consulta."""
    sefaz_mock.xml_resposta = XML_DISTRIBUICAO

    resp = run(
        client.post(
            "/api/v1/nfe/distribuicao",
            json={"cnpj": "99999999000199", "chave": CHAVE},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    assert resp.json()["tipo"] == "consChNFe"

    xml_enviado = sefaz_mock.chamadas[0][1]
    assert "<consChNFe>" in xml_enviado
    assert f"<chNFe>{CHAVE}</chNFe>" in xml_enviado


def test_distribuicao_sem_documento_retorna_422(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """É obrigatório informar cnpj ou cpf."""
    resp = run(
        client.post(
            "/api/v1/nfe/distribuicao",
            json={"nsu": 0},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 422
    assert len(sefaz_mock.chamadas) == 0


# ---------------------------------------------------------------------------
# Consulta de cadastro (CadConsultaCadastro4)
# ---------------------------------------------------------------------------


def test_consultar_cadastro(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """Consulta cadastro por CNPJ retorna os contribuintes localizados."""
    sefaz_mock.xml_resposta = XML_CADASTRO

    resp = run(
        client.get(
            "/api/v1/nfe/cadastro",
            params={"uf": "PR", "documento": "99999999000199"},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cstat"] == "111"
    assert data["tipo_documento"] == "CNPJ"
    assert data["contribuintes"] and data["contribuintes"][0]["cnpj"] == "99999999000199"
    assert data["contribuintes"][0]["razao_social"] == "Empresa Teste LTDA"
    assert data["contribuintes"][0]["uf"] == "PR"
    assert data["contribuintes"][0]["municipio"] == "Paranavaí"

    # O XML enviado contém ConsCad com UF e CNPJ
    xml_enviado = sefaz_mock.chamadas[0][1]
    assert "<UF>PR</UF>" in xml_enviado
    assert "<CNPJ>99999999000199</CNPJ>" in xml_enviado


def test_consultar_cadastro_tipo_invalido_retorna_422(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """tipo fora de CNPJ/CPF/IE é rejeitado (422)."""
    resp = run(
        client.get(
            "/api/v1/nfe/cadastro",
            params={"uf": "PR", "documento": "99999999000199", "tipo": "RG"},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 422
    assert len(sefaz_mock.chamadas) == 0


# ---------------------------------------------------------------------------
# Evento de operação não realizada (110112)
# ---------------------------------------------------------------------------


def test_operacao_nao_realizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Cenário feliz: evento 110112 enviado, registrado e nota continua AUTORIZADA."""
    run(_criar_nota(db, empresa_id=empresa.id))
    sefaz_mock.xml_resposta = XML_EVENTO_REGISTRADO

    resp = run(
        client.post(
            "/api/v1/nfe/operacao-nao-realizada",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tp_evento"] == "110112"
    assert data["status"] == "REGISTRADO"
    assert data["cstat"] == "135"
    assert data["modelo"] == "55"
    assert len(sefaz_mock.chamadas) == 1

    status, eventos = run(_ler_nota(db))
    assert status == "AUTORIZADA"  # operação não realizada não altera o status
    assert eventos and eventos[0]["tp_evento"] == "110112"
    assert eventos[0]["justificativa"] == JUSTIFICATIVA

    # O XML do evento enviado contém tpEvento 110112 e xJust
    xml_enviado = sefaz_mock.chamadas[0][1]
    assert "<tpEvento>110112</tpEvento>" in xml_enviado
    assert "<xJust>" in xml_enviado


def test_operacao_nao_realizada_nota_nao_autorizada_retorna_409(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Evento 110112 exige nota autorizada (409 em outros estados)."""
    run(_criar_nota(db, empresa_id=empresa.id, status="CANCELADA"))

    resp = run(
        client.post(
            "/api/v1/nfe/operacao-nao-realizada",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 409
    assert len(sefaz_mock.chamadas) == 0


def test_operacao_nao_realizada_nota_inexistente_retorna_404(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """Chave sem nota cadastrada retorna 404."""
    resp = run(
        client.post(
            "/api/v1/nfe/operacao-nao-realizada",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 404
    assert len(sefaz_mock.chamadas) == 0
