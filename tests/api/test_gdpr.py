"""Testes de LGPD: criptografia do destinatário, anonimização e auditoria."""

from __future__ import annotations

from tests.api.conftest import XML_SEFAZ_AUTORIZADA, authorization_headers, run

CPF = "12345678900"


async def _criar_nota(db, *, empresa_id, destinatario, destinatario_enc, chave):
    """Insere uma nota com destinatário (hash + criptografado) e XMLs."""
    from api.models import NotaFiscal

    async with db() as session:
        nota = NotaFiscal(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=111,
            serie=1,
            modelo="55",
            status="AUTORIZADA",
            destinatario=destinatario,
            destinatario_cpf_encrypted=destinatario_enc,
            xml_assinado="<NFe>assinado</NFe>",
            xml_protocolado="<nfeProc>protocolado</nfeProc>",
        )
        session.add(nota)
        await session.commit()
        return nota


async def _ler_nota(db, nota_id):
    from uuid import UUID

    from sqlalchemy import select

    from api.models import NotaFiscal

    if isinstance(nota_id, str):
        nota_id = UUID(nota_id)
    async with db() as session:
        return (
            await session.execute(select(NotaFiscal).where(NotaFiscal.id == nota_id))
        ).scalar_one()


# ---------------------------------------------------------------------------
# Criptografia em repouso (emissão)
# ---------------------------------------------------------------------------


def test_emissao_salva_destinatario_criptografado(
    client, empresa, api_client, auth_token, sefaz_mock, redis_fake, db, payload_nfe
):
    """Na emissão, o CPF do destinatário é criptografado (Fernet) + hash no banco."""
    sefaz_mock.xml_resposta = XML_SEFAZ_AUTORIZADA

    resp = run(
        client.post(
            "/api/v1/nfe/emitir",
            json=payload_nfe,
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 200

    from api.utils.crypto import decrypt_senha, hash_documento

    nota = run(_ler_nota(db, resp.json()["id"]))
    # Nada em claro: o campo destinatario guarda o hash, o dado pessoal é criptografado
    assert nota.destinatario != "12345678900"
    assert nota.destinatario == hash_documento("12345678900")
    assert nota.destinatario_cpf_encrypted
    assert nota.destinatario_cpf_encrypted != "12345678900"
    # Leitura descriptografa corretamente
    assert decrypt_senha(nota.destinatario_cpf_encrypted) == "12345678900"


# ---------------------------------------------------------------------------
# Anonimização
# ---------------------------------------------------------------------------


def test_anonimizar_solicitante_remove_dado_pessoal_e_mantem_xmls(
    client, empresa, api_client, auth_token, db
):
    """DELETE /gdpr/solicitante/{cpf} anonimiza e mantém XMLs (obrigação fiscal)."""
    from api.utils.crypto import encrypt_senha, hash_documento

    nota = run(
        _criar_nota(
            db,
            empresa_id=empresa.id,
            destinatario=hash_documento(CPF),
            destinatario_enc=encrypt_senha(CPF),
            chave="35111111111111111111111111111111111111111111",
        )
    )

    resp = run(
        client.delete(
            f"/api/v1/gdpr/solicitante/{CPF}",
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["registros_anonimizados"] == 1
    assert data["xmls_mantidos"] == 1
    assert data["status"] == "processada"
    assert data["documento_hash"] == hash_documento(CPF)

    # Dado pessoal removido, XMLs e hash preservados
    nota_atualizada = run(_ler_nota(db, nota.id))
    assert nota_atualizada.destinatario_cpf_encrypted is None
    assert nota_atualizada.destinatario == hash_documento(CPF)
    assert nota_atualizada.xml_assinado == "<NFe>assinado</NFe>"
    assert nota_atualizada.xml_protocolado == "<nfeProc>protocolado</nfeProc>"


def test_anonimizar_documento_invalido_retorna_400(client, empresa, api_client, auth_token):
    """Documento com tamanho/forma inválida retorna 400."""
    resp = run(
        client.delete(
            "/api/v1/gdpr/solicitante/123",
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 400


def test_status_solicitacao_rota(client, empresa, api_client, auth_token, db):
    """GET /gdpr/solicitacao/{id} retorna o status da solicitação."""
    from api.utils.crypto import hash_documento

    run(
        _criar_nota(
            db,
            empresa_id=empresa.id,
            destinatario=hash_documento(CPF),
            destinatario_enc="enc",
            chave="35111111111111111111111111111111111111111111",
        )
    )
    delete_resp = run(
        client.delete(
            f"/api/v1/gdpr/solicitante/{CPF}",
            headers=authorization_headers(auth_token),
        )
    )
    assert delete_resp.status_code == 200

    resp = run(
        client.get(
            f"/api/v1/gdpr/solicitacao/{delete_resp.json()['id']}",
            headers=authorization_headers(auth_token),
        )
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processada"
    assert data["registros_anonimizados"] == 1


# ---------------------------------------------------------------------------
# Auditoria (middleware)
# ---------------------------------------------------------------------------


def test_middleware_registra_ip_e_client_id(client, empresa, api_client, auth_token, caplog):
    """O middleware de auditoria loga ip e api_client_id sem o payload."""
    with caplog.at_level("INFO", logger="api.request"):
        resp = run(client.get("/api/v1/nfe/listar", headers=authorization_headers(auth_token)))
    assert resp.status_code == 200

    linhas = [r.getMessage() for r in caplog.records if r.name == "api.request"]
    assert any("GET /api/v1/nfe/listar" in linha for linha in linhas)
    assert any("ip=" in linha and "client=" in linha for linha in linhas)
    assert any(str(api_client.id) in linha for linha in linhas)
    # Sanitização: payload não é logado
    assert not any("justificativa" in linha for linha in linhas)
