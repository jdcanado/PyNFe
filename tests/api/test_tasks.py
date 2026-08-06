"""Testes do poller/warmer (crons da Vercel) e do webhook de notas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.api.conftest import run

CHAVE = "35111111111111111111111111111111111111111111"
RECIBO = "123456789012345"

XML_RECIBO_AUTORIZADA = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <nfeResultMsg>
      <retConsReciNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
        <tpAmb>2</tpAmb>
        <verAplic>PR_4.00</verAplic>
        <nRec>123456789012345</nRec>
        <cStat>104</cStat>
        <xMotivo>Lote processado</xMotivo>
        <protNFe>
          <infProt>
            <tpAmb>2</tpAmb>
            <verAplic>PR_4.00</verAplic>
            <chNFe>35111111111111111111111111111111111111111111</chNFe>
            <nProt>351111111111111</nProt>
            <cStat>100</cStat>
            <xMotivo>Autorizado o uso da NF-e</xMotivo>
          </infProt>
        </protNFe>
      </retConsReciNFe>
    </nfeResultMsg>
  </soap:Body>
</soap:Envelope>
"""

XML_RECIBO_PROCESSANDO = XML_RECIBO_AUTORIZADA.replace("<cStat>104</cStat>", "<cStat>105</cStat>")


async def _criar_nota(db, *, empresa_id, chave=CHAVE, status="PROCESSANDO", recibo=RECIBO):
    """Cria uma nota e ajusta `updated_at` para simular pendência."""
    from api.models import NotaFiscal

    async with db() as session:
        nota = NotaFiscal(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=111,
            serie=1,
            modelo="55",
            status=status,
            recibo=recibo,
        )
        session.add(nota)
        await session.commit()
        return nota


async def _atualizar_updated_at(db, nota_id, quando: datetime):
    from sqlalchemy import select

    from api.models import NotaFiscal

    async with db() as session:
        nota = (
            await session.execute(select(NotaFiscal).where(NotaFiscal.id == nota_id))
        ).scalar_one()
        nota.updated_at = quando
        await session.commit()


# ---------------------------------------------------------------------------
# Warmer
# ---------------------------------------------------------------------------


def test_warmer_retorna_200_com_timestamp(client):
    """GET /api/v1/tasks/warmer retorna 200 com warm=True e timestamp."""
    resp = run(client.get("/api/v1/tasks/warmer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["warm"] is True
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Poller
# ---------------------------------------------------------------------------


def test_poller_processa_nota_processando_antiga(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db, monkeypatch
):
    """Nota PROCESSANDO há >30s é consultada na SEFAZ, finalizada e gera webhook."""
    nota = run(_criar_nota(db, empresa_id=empresa.id))
    run(_atualizar_updated_at(db, nota.id, datetime.now(timezone.utc) - timedelta(seconds=60)))
    sefaz_mock.xml_resposta = XML_RECIBO_AUTORIZADA

    webhooks = []

    async def _fake_webhook(n, r, db):
        webhooks.append((n, r))

    monkeypatch.setattr("api.services.webhook_service.disparar_webhook", _fake_webhook)

    resp = run(client.post("/api/v1/tasks/poller"))

    assert resp.status_code == 200
    assert resp.json() == {"processed": 1}
    assert len(sefaz_mock.chamadas) == 1

    # Nota foi finalizada e o webhook disparado
    from sqlalchemy import select

    from api.models import NotaFiscal

    async def _ler_status(nota_id):
        async with db() as session:
            nota_db = (
                await session.execute(select(NotaFiscal).where(NotaFiscal.id == nota_id))
            ).scalar_one()
            return nota_db.status

    assert run(_ler_status(nota.id)) == "AUTORIZADA"
    assert len(webhooks) == 1
    assert webhooks[0][1]["status"] == "AUTORIZADA"


def test_poller_ignora_nota_recente_e_outros_status(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db
):
    """Nota PROCESSANDO recente (<30s) e notas de outros status não são processadas."""
    nota_recente = run(_criar_nota(db, empresa_id=empresa.id, chave=CHAVE))
    run(
        _atualizar_updated_at(
            db, nota_recente.id, datetime.now(timezone.utc) - timedelta(seconds=10)
        )
    )
    run(
        _criar_nota(
            db,
            empresa_id=empresa.id,
            chave="35111111111111111111111111111111111111111112",
            status="AUTORIZADA",
        )
    )
    sefaz_mock.xml_resposta = XML_RECIBO_PROCESSANDO

    resp = run(client.post("/api/v1/tasks/poller"))

    assert resp.status_code == 200
    assert resp.json() == {"processed": 0}
    assert len(sefaz_mock.chamadas) == 0


def test_poller_mantem_processando_quando_lote_105(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db, monkeypatch
):
    """Lote ainda em processamento (cStat 105) mantém a nota como PROCESSANDO."""
    nota = run(_criar_nota(db, empresa_id=empresa.id))
    run(_atualizar_updated_at(db, nota.id, datetime.now(timezone.utc) - timedelta(seconds=60)))
    sefaz_mock.xml_resposta = XML_RECIBO_PROCESSANDO

    async def _fake_webhook(n, r, db):
        raise AssertionError("webhook não deve disparar sem status final")

    monkeypatch.setattr("api.services.webhook_service.disparar_webhook", _fake_webhook)

    resp = run(client.post("/api/v1/tasks/poller"))

    assert resp.status_code == 200
    assert resp.json() == {"processed": 1}

    from sqlalchemy import select

    from api.models import NotaFiscal

    async def _ler_status(nota_id):
        async with db() as session:
            nota_db = (
                await session.execute(select(NotaFiscal).where(NotaFiscal.id == nota_id))
            ).scalar_one()
            return nota_db.status

    assert run(_ler_status(nota.id)) == "PROCESSANDO"


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def test_disparar_webhook_post_para_url(db, empresa, monkeypatch):
    """disparar_webhook envia POST JSON para a URL configurada."""
    # URL da empresa (fallback global não é usado)
    from api.models import Empresa

    async def _configurar():
        async with db() as session:
            empresa_db = await session.get(Empresa, empresa.id)
            empresa_db.webhook_url = "https://hook.example/notify"
            await session.commit()

    run(_configurar())

    chamadas = []

    class _FakeResp:
        status_code = 200

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            chamadas.append((url, json, headers, timeout))
            return _FakeResp()

    monkeypatch.setattr("api.services.webhook_service.httpx.AsyncClient", _FakeAsyncClient)

    from api.services.webhook_service import disparar_webhook

    class _Nota:
        id = None
        empresa_id = empresa.id
        chave_acesso = CHAVE
        status = "AUTORIZADA"
        modelo = "55"

    async def _exec():
        async with db() as session:
            return await disparar_webhook(
                _Nota(), {"status": "AUTORIZADA", "final": True}, session, delays=(0,)
            )

    ok = run(_exec())

    assert ok is True
    assert len(chamadas) == 1
    url, payload, _headers, _timeout = chamadas[0]
    assert url == "https://hook.example/notify"
    assert payload["event"] == "nfe.autorizada"
    assert payload["status"] == "AUTORIZADA"
    assert payload["chave_acesso"] == CHAVE
