"""Testes de integração dos eventos de NF-e/NFC-e (cancelamento, carta de correção, inutilização).

Cobre as rotas `POST /api/v1/nfe|nfce/{cancelar,carta-correcao,inutilizar}`:
- Cancelamento: nota muda para `CANCELADA` e o evento é registrado no JSONB.
- Nota já cancelada não pode ser cancelada novamente (409).
- Carta de correção: evento 110110 enviado e registrado.
- Inutilização: XML enviado com o Id no formato UF+ano+CNPJ+modelo+serie+faixa.
"""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run

CHAVE = "35111111111111111111111111111111111111111111"
JUSTIFICATIVA = "Cancelamento por erro na emissão"
CORRECAO = "Correção do endereço do destinatário"

XML_EVENTO_REGISTRADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
        <idLote>1</idLote>
        <tpEvento>110111</tpEvento>
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

XML_INUTILIZACAO_OK = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retInutNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
        <infInut>
          <tpAmb>2</tpAmb>
          <cUF>41</cUF>
          <ano>26</ano>
          <CNPJ>99999999000199</CNPJ>
          <mod>55</mod>
          <serie>1</serie>
          <nNFIni>1</nNFIni>
          <nNFFin>1</nNFFin>
          <cStat>102</cStat>
          <xMotivo>Inutilizacao de numero homologado</xMotivo>
          <nProt>135260000000002</nProt>
        </infInut>
      </retInutNFe>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""


async def _criar_nota(
    db,
    *,
    empresa_id,
    chave=CHAVE,
    modelo="55",
    status="AUTORIZADA",
    protocolo="351111111111111",
):
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
            protocolo=protocolo,
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
# Cancelamento (110111)
# ---------------------------------------------------------------------------


def test_cancelar_nfe_autorizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Cenário feliz: evento 110111 registrado e nota marcada como CANCELADA."""
    run(_criar_nota(db, empresa_id=empresa.id))
    sefaz_mock.xml_resposta = XML_EVENTO_REGISTRADO

    resp = run(
        client.post(
            "/api/v1/nfe/cancelar",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tp_evento"] == "110111"
    assert data["status"] == "CANCELADA"
    assert data["cstat"] == "135"
    assert data["xmotivo"] == "Evento registrado e vinculado a NF-e"
    assert data["nprot"] == "135260000000001"
    assert data["modelo"] == "55"
    assert len(sefaz_mock.chamadas) == 1

    status, eventos = run(_ler_nota(db))
    assert status == "CANCELADA"
    assert eventos and eventos[0]["tp_evento"] == "110111"
    assert eventos[0]["justificativa"] == JUSTIFICATIVA


def test_cancelar_nfce_autorizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Mesma operação para NFC-e (modelo 65)."""
    run(_criar_nota(db, empresa_id=empresa.id, modelo="65"))
    sefaz_mock.xml_resposta = XML_EVENTO_REGISTRADO

    resp = run(
        client.post(
            "/api/v1/nfce/cancelar",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    assert resp.json()["modelo"] == "65"
    status, _ = run(_ler_nota(db))
    assert status == "CANCELADA"


def test_cancelar_nota_ja_cancelada_retorna_409(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Regra de negócio: nota já cancelada não pode ser cancelada novamente."""
    run(_criar_nota(db, empresa_id=empresa.id, status="CANCELADA"))

    resp = run(
        client.post(
            "/api/v1/nfe/cancelar",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 409
    assert "cancelada" in resp.json()["detail"].lower()
    assert len(sefaz_mock.chamadas) == 0


def test_cancelar_nota_inexistente_retorna_404(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake
):
    """Chave de acesso sem nota cadastrada retorna 404."""
    resp = run(
        client.post(
            "/api/v1/nfe/cancelar",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 404


def test_cancelar_sem_certificado_retorna_400(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Empresa sem certificado cadastrado retorna 400."""
    run(_criar_nota(db, empresa_id=empresa.id))
    run(_remover_certificado(db, empresa.id))

    resp = run(
        client.post(
            "/api/v1/nfe/cancelar",
            json={"chave_acesso": CHAVE, "justificativa": JUSTIFICATIVA},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 400
    assert "certificado" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Carta de correção (110110)
# ---------------------------------------------------------------------------


def test_carta_correcao_nfe_autorizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Cenário feliz: evento 110110 enviado e registrado no JSONB."""
    run(_criar_nota(db, empresa_id=empresa.id))
    sefaz_mock.xml_resposta = XML_EVENTO_REGISTRADO

    resp = run(
        client.post(
            "/api/v1/nfe/carta-correcao",
            json={"chave_acesso": CHAVE, "correcao": CORRECAO},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tp_evento"] == "110110"
    assert data["status"] == "REGISTRADO"
    assert data["cstat"] == "135"

    status, eventos = run(_ler_nota(db))
    assert status == "AUTORIZADA"  # carta de correção não altera o status
    assert eventos and eventos[0]["tp_evento"] == "110110"
    assert eventos[0]["correcao"] == CORRECAO


def test_carta_correcao_nota_nao_autorizada_retorna_409(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Carta de correção exige nota autorizada (409 em outros estados)."""
    run(_criar_nota(db, empresa_id=empresa.id, status="CANCELADA"))

    resp = run(
        client.post(
            "/api/v1/nfe/carta-correcao",
            json={"chave_acesso": CHAVE, "correcao": CORRECAO},
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 409
    assert len(sefaz_mock.chamadas) == 0


# ---------------------------------------------------------------------------
# Inutilização
# ---------------------------------------------------------------------------


def test_inutilizar_nfe(client, empresa, api_client, auth_token, sefaz_mock, redis_fake):
    """Inutilização homologada: XML enviado com Id no formato da SEFAZ."""
    sefaz_mock.xml_resposta = XML_INUTILIZACAO_OK

    resp = run(
        client.post(
            "/api/v1/nfe/inutilizar",
            json={
                "cnpj": "99999999000199",
                "serie": 1,
                "numero_inicial": 1,
                "numero_final": 1,
                "justificativa": "Inutilização por erro de numeração",
            },
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "INUTILIZADA"
    assert data["cstat"] == "102"
    assert data["nprot"] == "135260000000002"
    assert data["modelo"] == "55"
    assert len(sefaz_mock.chamadas) == 1

    # Id da inutilização: ID + UF + ano + CNPJ + modelo + série + numInicial + numFinal
    xml_enviado = sefaz_mock.chamadas[0][1]
    assert 'Id="ID41269999999900019955001000000001000000001"' in xml_enviado
