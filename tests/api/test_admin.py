"""Testes das rotas administrativas e da documentação OpenAPI."""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run


async def _tornar_admin(db, api_client_id) -> None:
    """Eleva o API client ao plano admin."""
    from api.models import APIClient

    async with db() as session:
        client = await session.get(APIClient, api_client_id)
        client.plano = "admin"
        await session.commit()


async def _criar_nota(db, *, empresa_id, status="AUTORIZADA", chave):
    from api.models import NotaFiscal

    async with db() as session:
        nota = NotaFiscal(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=111,
            serie=1,
            modelo="55",
            status=status,
        )
        session.add(nota)
        await session.commit()


# ---------------------------------------------------------------------------
# Estatísticas
# ---------------------------------------------------------------------------


def test_estatisticas_retorna_metricas(client, db, empresa, api_client, auth_token):
    """GET /admin/estatisticas retorna totais, taxa de autorização e top clients."""
    run(_tornar_admin(db, api_client.id))
    run(
        _criar_nota(
            db,
            empresa_id=empresa.id,
            status="AUTORIZADA",
            chave="35111111111111111111111111111111111111111111",
        )
    )
    run(
        _criar_nota(
            db,
            empresa_id=empresa.id,
            status="REJEITADA",
            chave="35111111111111111111111111111111111111111112",
        )
    )

    resp = run(client.get("/api/v1/admin/estatisticas", headers=authorization_headers(auth_token)))

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_notas"] == 2
    assert data["taxa_autorizacao_percent"] == 50.0
    assert data["total_notas_hoje"] >= 0
    assert "top_api_clients" in data
    assert "rate_limit_enabled" in data
    assert isinstance(data["top_api_clients"], list)


def test_estatisticas_sem_admin_retorna_403(client, empresa, api_client, auth_token):
    """Client sem plano admin recebe 403."""
    resp = run(client.get("/api/v1/admin/estatisticas", headers=authorization_headers(auth_token)))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------


def test_listar_api_clients(client, db, empresa, api_client, auth_token):
    """GET /admin/api-clients lista os API clients da empresa."""
    run(_tornar_admin(db, api_client.id))

    resp = run(client.get("/api/v1/admin/api-clients", headers=authorization_headers(auth_token)))

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(item["id"] == str(api_client.id) for item in data)
    assert data[0]["plano"] == "admin"


# ---------------------------------------------------------------------------
# OpenAPI / docs
# ---------------------------------------------------------------------------


def test_openapi_titulo_e_tags_em_portugues(client):
    """OpenAPI carrega com título e tags descritas em português."""
    resp = run(client.get("/openapi.json"))
    assert resp.status_code == 200
    data = resp.json()

    assert data["info"]["title"] == "PyNFe API"
    assert data["info"]["version"] == "1.0.0"
    assert "documentação" in data["info"]["description"].lower()

    tags = {t["name"] for t in data.get("tags", [])}
    assert {"nfe", "nfce", "gtin", "empresa", "auth", "admin"} <= tags
    # descrições em português
    descricao_nfe = next(t["description"] for t in data["tags"] if t["name"] == "nfe")
    assert "NF-e" in descricao_nfe


def test_docs_swagger_disponivel(client):
    """A rota /docs (Swagger UI) responde."""
    resp = run(client.get("/docs"))
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower()
