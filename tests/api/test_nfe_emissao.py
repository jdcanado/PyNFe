"""Testes de integração da emissão de NF-e (POST /api/v1/nfe/emitir)."""

from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import XML_SEFAZ_AUTORIZADA, authorization_headers, run

XML_SEFAZ_REJEITADA = XML_SEFAZ_AUTORIZADA.replace("<cStat>100</cStat>", "<cStat>110</cStat>")


def test_emitir_nfe_autorizada(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, payload_nfe
):
    """Cenário feliz: SEFAZ autoriza e a nota é persistida para a empresa do client."""
    # empresa_id do payload é ignorado: a rota usa a empresa do client autenticado
    payload_nfe["empresa_id"] = str(uuid4())

    resp = run(
        client.post(
            "/api/v1/nfe/emitir",
            json=payload_nfe,
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "AUTORIZADA"
    assert data["protocolo"] == "351111111111111"
    assert len(data["chave_acesso"]) == 44
    assert data["numero"] == 111
    assert data["serie"] == 1
    assert data["modelo"] == "55"
    assert data["valor_total"] == 117.0
    assert data["id"] is not None
    # empresa derivada do client autenticado (payload foi sobrescrito)
    assert data["empresa_id"] == str(empresa.id)
    assert data["xml_assinado"] and "Signature" in data["xml_assinado"]
    assert data["xml_protocolado"] and "nfeProc" in data["xml_protocolado"]

    # SEFAZ foi chamada com o XML assinado
    assert len(sefaz_mock.chamadas) == 1


def test_emitir_nfe_sem_token_retorna_401(client, payload_nfe):
    """Cenário de erro: rota protegida sem token retorna 401."""
    resp = run(client.post("/api/v1/nfe/emitir", json=payload_nfe))
    assert resp.status_code == 401


def test_emitir_nfe_sem_certificado_retorna_400(
    client, db, api_client, auth_token, redis_fake, payload_nfe
):
    """Cenário de erro: empresa sem certificado cadastrado retorna 400."""
    # Remove o certificado da empresa
    run(_remover_certificado(db, payload_nfe["empresa_id"]))

    resp = run(
        client.post(
            "/api/v1/nfe/emitir",
            json=payload_nfe,
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 400
    assert "certificado" in resp.json()["detail"]


def test_emitir_nfe_sefaz_rejeita(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, payload_nfe
):
    """Cenário de erro: SEFAZ rejeita a nota (cStat 110) e ela é persistida como REJEITADA."""
    sefaz_mock.xml_resposta = XML_SEFAZ_REJEITADA

    resp = run(
        client.post(
            "/api/v1/nfe/emitir",
            json=payload_nfe,
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "REJEITADA"
    assert data["cstat"] == "110"
    assert data["xmotivo"]  # motivo exposto pela SEFAZ (não mais "<Response [200]>")
    assert data["xml_protocolado"] and "nfeProc" in data["xml_protocolado"]


def test_emitir_nfe_payload_invalido(client, empresa, api_client, auth_token):
    """Cenário de erro: payload com validação falha retorna 422."""
    payload = {"empresa_id": str(empresa.id), "uf": "P"}  # UF inválida e sem campos obrigatórios
    resp = run(
        client.post(
            "/api/v1/nfe/emitir",
            json=payload,
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 422


async def _remover_certificado(db, empresa_id: str) -> None:
    """Remove cert_pem/key_pem da empresa no banco de teste."""
    from uuid import UUID

    from sqlalchemy import select

    from api.models import Empresa

    async with db() as session:
        empresa = (
            await session.execute(select(Empresa).where(Empresa.id == UUID(empresa_id)))
        ).scalar_one()
        empresa.cert_pem = None
        empresa.key_pem = None
        await session.commit()
