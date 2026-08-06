"""Testes de integração do rate limit (429, headers e cache do plano)."""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run


def test_rate_limit_sem_jwt_limita_por_ip(client):
    """31 requests sem JWT: o 31º estoura o limite free (30/min) e retorna 429."""
    for _ in range(30):
        resp = run(client.get("/api/v1/health"))
        assert resp.status_code == 200

    resp = run(client.get("/api/v1/health"))
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limit_exceeded"
    assert resp.headers["X-RateLimit-Limit"] == "30"
    assert resp.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_com_jwt_limita_por_client_e_cacheia_plano(
    client, api_client, auth_token, redis_fake
):
    """Com JWT o limite é por client_id; o plano é cacheado no KV (sem SELECT)."""
    # Primeira chamada popula o cache do plano
    resp = run(client.get("/api/v1/health", headers=authorization_headers(auth_token)))
    assert resp.status_code == 200

    # Plano cacheado no KV
    cache_key = f"ratelimit:plano:{api_client.id}"
    assert cache_key in redis_fake.store
    assert redis_fake.store[cache_key] == "free"

    # Estoura o limite free (30/min): chamadas 2 a 30 no loop
    for _ in range(29):
        resp = run(client.get("/api/v1/health", headers=authorization_headers(auth_token)))
        assert resp.status_code == 200

    resp = run(client.get("/api/v1/health", headers=authorization_headers(auth_token)))
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Limit"] == "30"
