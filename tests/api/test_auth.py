"""Testes de integração da autenticação (POST /api/v1/auth/token)."""

from __future__ import annotations

from tests.api.conftest import run


def test_token_com_credenciais_validas(client, api_client):
    """Cenário feliz: api-key (prefixo) + api-secret válidos retornam JWT."""
    resp = run(
        client.post(
            "/api/v1/auth/token",
            headers={
                "api-key": api_client.api_key_prefix,
                "api-secret": "segredo-da-chave",
            },
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["api_key_prefix"] == api_client.api_key_prefix


def test_token_com_api_key_inexistente(client, api_client):
    """Cenário de erro: prefixo desconhecido retorna 401."""
    resp = run(
        client.post(
            "/api/v1/auth/token",
            headers={
                "api-key": "prefixo-inexistente",
                "api-secret": "segredo-da-chave",
            },
        )
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_token_com_secret_invalido(client, api_client):
    """Cenário de erro: secret incorreto retorna 401."""
    resp = run(
        client.post(
            "/api/v1/auth/token",
            headers={
                "api-key": api_client.api_key_prefix,
                "api-secret": "segredo-errado",
            },
        )
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_token_sem_headers(client):
    """Cenário de erro: sem os headers obrigatórios retorna 422."""
    resp = run(client.post("/api/v1/auth/token"))
    assert resp.status_code == 422
