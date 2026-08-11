"""Testes da criação de empresa via admin (POST /api/v1/admin/empresa)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.models import APIClient, Empresa
from tests.api.conftest import authorization_headers, run

CSC_VALIDO = "0123456789abcdef0123456789abcdef0123"  # 36 caracteres
CSC_ID_VALIDO = "000002"


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


def _payload(cnpj: str = "11111111000111", **kwargs) -> dict:
    base = {"cnpj": cnpj, "razao_social": "Empresa Nova LTDA", "uf": "SP"}
    base.update(kwargs)
    return base


def test_criar_empresa_admin_sucesso(client, db, admin_token):
    """Admin cria empresa com CSC opcional: 201 + credenciais + persistência."""
    payload = _payload(csc=CSC_VALIDO, csc_id=CSC_ID_VALIDO, client_name="Client Nova")
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=payload,
            headers=authorization_headers(admin_token),
        )
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["empresa_id"]
    assert data["api_key"] and data["api_secret"]
    assert data["csc_id"] == CSC_ID_VALIDO
    assert data["csc_mascarado"] == CSC_VALIDO[:4] + "*" * 32

    # Persistência: Empresa + APIClient (plano free) criados
    async def _check():
        async with db() as session:
            emp = (
                await session.execute(select(Empresa).where(Empresa.cnpj == payload["cnpj"]))
            ).scalar_one()
            clients = (
                (await session.execute(select(APIClient).where(APIClient.empresa_id == emp.id)))
                .scalars()
                .all()
            )
            return emp, clients

    emp, clients = run(_check())
    assert emp.csc == CSC_VALIDO
    assert emp.csc_id == CSC_ID_VALIDO
    assert len(clients) == 1
    assert clients[0].plano == "free"
    assert clients[0].is_active is True


def test_criar_empresa_sem_csc(client, db, admin_token):
    """CSC é opcional na criação: empresa criada sem campos de NFC-e."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj="22222222000122"),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["csc_id"] is None
    assert data["csc_mascarado"] is None


def test_criar_empresa_sem_token_401(client):
    """Rota protegida: sem token retorna 401."""
    resp = run(client.post("/api/v1/admin/empresa", json=_payload()))
    assert resp.status_code == 401


def test_criar_empresa_client_free_403(client, auth_token):
    """Client com plano free não pode criar empresa (403)."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(),
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 403


def test_criar_empresa_cnpj_duplicado_409(client, admin_token, empresa):
    """CNPJ já cadastrado retorna 409 (Conflito)."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj=empresa.cnpj),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 409
    assert "CNPJ" in resp.json()["detail"]


def test_criar_empresa_csc_invalido_422(client, admin_token):
    """CSC fora do padrão (36 chars) e CSC ID fora do padrão (6 dígitos) → 422."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj="33333333000133", csc="curto", csc_id="123"),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 422


def test_criar_empresa_csc_uuid_homologacao(client, admin_token):
    """CSC de homologação SEFAZ em formato UUID (com hífens) é aceito."""
    csc_uuid = "a3ce282f-2bf1-4b64-a55b-b4f1faa39683"
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj="44444444000144", csc=csc_uuid, csc_id="000003"),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["csc_id"] == "000003"
    assert data["csc_mascarado"] == csc_uuid[:4] + "*" * 32


def test_criar_empresa_com_crt(client, db, admin_token):
    """CRT (regime tributário) é aceito na criação e persistido no banco."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj="55555555000155", codigo_regime_tributario="1"),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 201

    async def _check():
        async with db() as session:
            return (
                await session.execute(select(Empresa).where(Empresa.cnpj == "55555555000155"))
            ).scalar_one()

    emp = run(_check())
    assert emp.codigo_regime_tributario == "1"


def test_criar_empresa_crt_invalido_422(client, admin_token):
    """CRT fora de 1-4 é rejeitado pelo schema."""
    resp = run(
        client.post(
            "/api/v1/admin/empresa",
            json=_payload(cnpj="66666666000166", codigo_regime_tributario="9"),
            headers=authorization_headers(admin_token),
        )
    )
    assert resp.status_code == 422
