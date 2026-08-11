"""Testes do endpoint de migração do banco (POST /api/v1/admin/migrate)."""

from __future__ import annotations

import pytest

from api.models import APIClient
from tests.api.conftest import authorization_headers, run


@pytest.fixture
def admin_token(db, empresa):
    """JWT de um API client com plano admin."""
    from api.core.security import create_jwt_token

    async def _criar():
        async with db() as session:
            admin = APIClient(
                name="Admin Teste",
                api_key_hash="0" * 60,
                api_key_prefix="adm00001",
                plano="admin",
                is_active=True,
                empresa_id=empresa.id,
            )
            session.add(admin)
            await session.commit()
            await session.refresh(admin)
            return admin

    client = run(_criar())
    return create_jwt_token(str(client.id))


def test_migrar_sem_token_401(client):
    """Rota protegida: sem token retorna 401."""
    resp = run(client.post("/api/v1/admin/migrate"))
    assert resp.status_code == 401


def test_migrar_client_free_403(client, auth_token):
    """Client com plano free não pode migrar (403)."""
    resp = run(client.post("/api/v1/admin/migrate", headers=authorization_headers(auth_token)))
    assert resp.status_code == 403


def test_migrar_admin_200(client, admin_token, monkeypatch):
    """Admin dispara a migração e recebe a lista de tabelas."""

    async def fake_migrar():
        return ["api_clients", "empresas"]

    monkeypatch.setattr("api.routers.admin.migrar", fake_migrar)
    resp = run(client.post("/api/v1/admin/migrate", headers=authorization_headers(admin_token)))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "empresas" in data["tabelas"]
