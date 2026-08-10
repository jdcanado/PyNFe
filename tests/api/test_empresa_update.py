"""Testes de atualização da empresa (PUT /api/v1/empresa)."""

from __future__ import annotations

from uuid import uuid4

from api.models import APIClient, Empresa
from tests.api.conftest import authorization_headers, run

CSC_VALIDO = "0123456789abcdef0123456789abcdef0123"  # 36 caracteres
CSC_ID_VALIDO = "000002"


def test_atualizar_empresa_sucesso(client, db, empresa, auth_token):
    """Empresa do token atualiza CSC/CSC ID e dados: 200 + persistência."""
    payload = {
        "nome_fantasia": "Fantasia Nova",
        "uf": "PR",
        "csc": CSC_VALIDO,
        "csc_id": CSC_ID_VALIDO,
    }
    resp = run(
        client.put(
            "/api/v1/empresa",
            json=payload,
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["empresa_id"] == str(empresa.id)
    assert data["nome_fantasia"] == "Fantasia Nova"
    assert data["csc_id"] == CSC_ID_VALIDO
    assert data["csc_mascarado"] == CSC_VALIDO[:4] + "*" * 32
    assert data["csc_mascarado"] != CSC_VALIDO  # nunca ecoa o CSC completo

    # Persistência no banco
    async def _check():
        async with db() as session:
            return await session.get(Empresa, empresa.id)

    emp = run(_check())
    assert emp.csc == CSC_VALIDO
    assert emp.csc_id == CSC_ID_VALIDO
    assert emp.nome_fantasia == "Fantasia Nova"


def test_atualizar_empresa_parcial(client, db, empresa, auth_token):
    """Enviar só o CSC ID não altera o CSC atual."""
    resp = run(
        client.put(
            "/api/v1/empresa",
            json={"csc_id": CSC_ID_VALIDO},
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["csc_id"] == CSC_ID_VALIDO

    async def _check():
        async with db() as session:
            return await session.get(Empresa, empresa.id)

    emp = run(_check())
    assert emp.csc == empresa.csc  # inalterado (CSC do fixture)
    assert emp.csc_id == CSC_ID_VALIDO


def test_atualizar_sem_token_401(client):
    """Rota protegida: sem token retorna 401."""
    resp = run(client.put("/api/v1/empresa", json={"csc": CSC_VALIDO}))
    assert resp.status_code == 401


def test_atualizar_empresa_inexistente_404(client, db):
    """Client vinculado a uma empresa inexistente retorna 404."""
    from api.core.security import create_jwt_token

    async def _criar():
        async with db() as session:
            orfao = APIClient(
                name="Client Orfao",
                api_key_hash="1" * 60,
                api_key_prefix="orf00001",
                is_active=True,
                empresa_id=uuid4(),
            )
            session.add(orfao)
            await session.commit()
            await session.refresh(orfao)
            return orfao

    orfao = run(_criar())
    token = create_jwt_token(str(orfao.id))
    resp = run(
        client.put(
            "/api/v1/empresa",
            json={"csc": CSC_VALIDO},
            headers=authorization_headers(token),
        )
    )
    assert resp.status_code == 404


def test_atualizar_csc_invalido_422(client, auth_token):
    """CSC fora do padrão retorna 422."""
    resp = run(
        client.put(
            "/api/v1/empresa",
            json={"csc": "abc"},
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 422
