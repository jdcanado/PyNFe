"""Testes do webhook_service (retry/backoff, HMAC, logs) e das rotas de gestão."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from tests.api.conftest import authorization_headers, run

CHAVE = "35111111111111111111111111111111111111111111"
SECRET = "segredo-teste"
URL = "https://hook.example/notify"


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Cliente httpx fake com fila de respostas (uma por tentativa)."""

    def __init__(self, respostas: list[int]) -> None:
        self._respostas = list(respostas)
        self.chamadas: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append((url, json, headers, timeout))
        status = self._respostas.pop(0) if self._respostas else 500
        return _FakeResp(status)


class _Nota:
    """Nota sintética para disparar o webhook."""

    def __init__(self, empresa_id, *, modelo="55", status="AUTORIZADA"):
        self.id = None
        self.empresa_id = empresa_id
        self.chave_acesso = CHAVE
        self.modelo = modelo
        self.status = status


async def _configurar_webhook(db, empresa_id, url=URL, secret=SECRET):
    from api.models import Empresa

    async with db() as session:
        empresa = await session.get(Empresa, empresa_id)
        empresa.webhook_url = url
        empresa.webhook_secret = secret
        await session.commit()


async def _ultimos_logs(db, empresa_id, limite=10):
    from sqlalchemy import select

    from api.models import WebhookLog

    async with db() as session:
        result = await session.execute(
            select(WebhookLog)
            .where(WebhookLog.empresa_id == empresa_id)
            .order_by(WebhookLog.created_at)
            .limit(limite)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# webhook_service: retry, HMAC e logs
# ---------------------------------------------------------------------------


def test_webhook_sucesso_na_primeira_tentativa(db, empresa, monkeypatch):
    """HTTP 2xx na 1ª tentativa: sucesso, 1 chamada, log com sucesso=True."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([200])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    async def _exec():
        from api.services.webhook_service import disparar_webhook

        async with db() as session:
            return await disparar_webhook(
                _Nota(empresa.id), {"status": "AUTORIZADA", "final": True}, session, delays=(0,)
            )

    assert run(_exec()) is True
    assert len(fake.chamadas) == 1

    logs = run(_ultimos_logs(db, empresa.id))
    assert len(logs) == 1
    assert logs[0].sucesso is True
    assert logs[0].tentativa == 1
    assert logs[0].status_code == 200
    assert logs[0].event == "nfe.autorizada"


def test_webhook_retry_sucesso_na_segunda_tentativa(db, empresa, monkeypatch):
    """Falha na 1ª tentativa e sucesso na 2ª (backoff injetado como 0)."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([500, 200])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    async def _exec():
        from api.services.webhook_service import disparar_webhook

        async with db() as session:
            return await disparar_webhook(
                _Nota(empresa.id), {"status": "AUTORIZADA"}, session, delays=(0, 0)
            )

    assert run(_exec()) is True
    assert len(fake.chamadas) == 2

    logs = run(_ultimos_logs(db, empresa.id))
    assert len(logs) == 2
    assert logs[0].sucesso is False
    assert logs[0].status_code == 500
    assert logs[0].tentativa == 1
    assert logs[1].sucesso is True
    assert logs[1].tentativa == 2


def test_webhook_tres_falhas_retorna_failed(db, empresa, monkeypatch):
    """3 falhas consecutivas: retorna False e registra 3 logs (último sucesso=False)."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([500, 503, 500])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    async def _exec():
        from api.services.webhook_service import disparar_webhook

        async with db() as session:
            return await disparar_webhook(
                _Nota(empresa.id), {"status": "AUTORIZADA"}, session, delays=(0, 0, 0)
            )

    assert run(_exec()) is False
    assert len(fake.chamadas) == 3

    logs = run(_ultimos_logs(db, empresa.id))
    assert len(logs) == 3
    assert all(log.sucesso is False for log in logs)
    assert logs[-1].tentativa == 3


def test_webhook_assinatura_hmac_confere(db, empresa, monkeypatch):
    """O header X-Webhook-Signature é HMAC-SHA256 do payload com o secret."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([200])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    async def _exec():
        from api.services.webhook_service import disparar_webhook

        async with db() as session:
            return await disparar_webhook(
                _Nota(empresa.id), {"status": "AUTORIZADA"}, session, delays=(0,)
            )

    assert run(_exec()) is True
    _, payload, headers, _timeout = fake.chamadas[0]

    assinatura_recebida = headers["X-Webhook-Signature"]
    corpo = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    esperado = hmac.new(SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    assert assinatura_recebida == esperado


# ---------------------------------------------------------------------------
# Rotas: config, logs e test
# ---------------------------------------------------------------------------


def test_webhook_config_rota(client, empresa, api_client, auth_token, db):
    """POST /webhooks/config atualiza URL e secret da empresa (secret mascarado)."""
    resp = run(
        client.post(
            "/api/v1/webhooks/config",
            json={"webhook_url": URL, "webhook_secret": SECRET},
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["webhook_url"] == URL
    assert data["webhook_secret"] == "********"


def test_webhook_logs_rota(client, empresa, api_client, auth_token, db, monkeypatch):
    """GET /webhooks/logs retorna o histórico de entregas da empresa."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([200])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    async def _disparar():
        from api.services.webhook_service import disparar_webhook

        async with db() as session:
            await disparar_webhook(
                _Nota(empresa.id), {"status": "AUTORIZADA"}, session, delays=(0,)
            )

    run(_disparar())

    resp = run(client.get("/api/v1/webhooks/logs", headers=authorization_headers(auth_token)))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["event"] == "nfe.autorizada"
    assert item["sucesso"] is True
    assert item["status_code"] == 200


def test_webhook_test_rota(client, empresa, api_client, auth_token, db, monkeypatch):
    """POST /webhooks/test envia um evento de teste para a URL configurada."""
    run(_configurar_webhook(db, empresa.id))
    fake = _FakeAsyncClient([200])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)

    resp = run(client.post("/api/v1/webhooks/test", headers=authorization_headers(auth_token)))
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["event"] == "nfe.autorizada"
    assert len(fake.chamadas) == 1
