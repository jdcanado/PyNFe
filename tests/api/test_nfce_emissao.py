"""Testes de integração da NFC-e (POST /api/v1/nfce/emitir e consulta)."""

from __future__ import annotations

from tests.api.conftest import authorization_headers, run


def test_emitir_nfce_autorizada_com_qrcode(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, payload_nfce
):
    """Cenário feliz: SEFAZ autoriza; resposta com chave e URL do QR Code."""
    resp = run(
        client.post(
            "/api/v1/nfce/emitir",
            json=payload_nfce,
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "AUTORIZADA"
    assert data["modelo"] == "65"
    assert len(data["chave_acesso"]) == 44
    assert data["qrcode_url"] and "qrcode" in data["qrcode_url"]
    assert data["xml_assinado"] and "<mod>65</mod>" in data["xml_assinado"]
    assert data["id"] is not None

    # Consulta pela chave retorna a mesma NFC-e
    resp2 = run(
        client.get(
            f"/api/v1/nfce/consultar/{data['chave_acesso']}",
            headers=authorization_headers(auth_token),
        )
    )
    assert resp2.status_code == 200
    assert resp2.json()["chave_acesso"] == data["chave_acesso"]


def test_emitir_nfce_sem_token_retorna_401(client, payload_nfce):
    """Cenário de erro: rota protegida sem token retorna 401."""
    resp = run(client.post("/api/v1/nfce/emitir", json=payload_nfce))
    assert resp.status_code == 401


def test_consultar_nfce_nao_encontrada(client, empresa, api_client, auth_token):
    """Cenário de erro: chave inexistente retorna 404."""
    resp = run(
        client.get(
            f"/api/v1/nfce/consultar/{'3' * 44}",
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 404
