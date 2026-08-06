"""Testes de integração da listagem de notas (GET /api/v1/nfe/listar e /nfce/listar)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.api.conftest import authorization_headers, run


def _nota(
    empresa_id,
    chave: str,
    numero: int,
    status: str,
    emitida_em: datetime,
    modelo: str = "55",
    destinatario: str | None = "12345678900",
):
    from api.models import NotaFiscal

    return NotaFiscal(
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=numero,
        serie=1,
        modelo=modelo,
        status=status,
        protocolo="351111111111111",
        valor_total=100.0,
        emitida_em=emitida_em,
        natureza_operacao="VENDA",
        destinatario=destinatario,
    )


async def _inserir_notas(db, empresa_id, qtd: int, base: datetime | None = None):
    """Insere `qtd` notas com datas crescentes (dia a dia) a partir de `base`."""
    base = base or datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(qtd):
        await _adicionar_nota(
            db,
            _nota(
                empresa_id,
                f"{i + 1:044d}",
                i + 1,
                "AUTORIZADA" if i % 2 == 0 else "REJEITADA",
                base + timedelta(days=i),
            ),
        )


async def _adicionar_nota(db, nota) -> None:
    """Adiciona uma nota ao banco de teste e faz commit."""
    async with db() as session:
        session.add(nota)
        await session.commit()


def test_listar_paginado(client, db, empresa, api_client, auth_token):
    """GET /nfe/listar retorna lista paginada com metadados."""
    run(_inserir_notas(db, empresa.id, 25))

    resp = run(
        client.get(
            "/api/v1/nfe/listar",
            headers=authorization_headers(auth_token),
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 25
    assert data["size"] == 20
    assert data["page"] == 1
    assert data["pages"] == 2
    assert len(data["items"]) == 20
    # Ordenação por emissão DESC
    primeiro = data["items"][0]
    assert primeiro["chave_acesso"] == f"{25:044d}"


def test_listar_page_size(client, db, empresa, api_client, auth_token):
    """?page=2&size=10 retorna a página correta."""
    run(_inserir_notas(db, empresa.id, 25))

    resp = run(
        client.get(
            "/api/v1/nfe/listar",
            params={"page": 2, "size": 10},
            headers=authorization_headers(auth_token),
        )
    )

    data = resp.json()
    assert data["page"] == 2
    assert data["size"] == 10
    assert data["pages"] == 3
    assert len(data["items"]) == 10
    # página 2: notas 6 a 15 (ordem DESC)
    assert data["items"][0]["chave_acesso"] == f"{15:044d}"
    assert data["items"][-1]["chave_acesso"] == f"{6:044d}"


def test_listar_filtro_status(client, db, empresa, api_client, auth_token):
    """?status=autorizada filtra corretamente."""
    run(_inserir_notas(db, empresa.id, 10))

    resp = run(
        client.get(
            "/api/v1/nfe/listar",
            params={"status": "autorizada"},
            headers=authorization_headers(auth_token),
        )
    )

    data = resp.json()
    assert data["total"] == 5
    assert all(item["status"] == "AUTORIZADA" for item in data["items"])


def test_listar_filtro_periodo(client, db, empresa, api_client, auth_token):
    """?data_inicio & data_fim filtram por período."""
    run(_inserir_notas(db, empresa.id, 25))  # 2026-01-01 a 2026-01-25

    resp = run(
        client.get(
            "/api/v1/nfe/listar",
            params={"data_inicio": "2026-01-05", "data_fim": "2026-01-10"},
            headers=authorization_headers(auth_token),
        )
    )

    data = resp.json()
    assert data["total"] == 6  # dias 5..10
    assert len(data["items"]) == 6


def test_listar_filtro_destinatario(client, db, empresa, api_client, auth_token):
    """?destinatario filtra pelo CNPJ/CPF do destinatário (hash no banco — LGPD)."""
    from api.utils.crypto import hash_documento

    run(_inserir_notas(db, empresa.id, 5))
    # adiciona uma nota com destinatário diferente (banco guarda apenas o hash)
    run(
        _adicionar_nota(
            db,
            _nota(
                empresa.id,
                f"{99:044d}",
                99,
                "AUTORIZADA",
                datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc),
                destinatario=hash_documento("98765432100"),
            ),
        )
    )

    resp = run(
        client.get(
            "/api/v1/nfe/listar",
            params={"destinatario": "98765432100"},
            headers=authorization_headers(auth_token),
        )
    )

    data = resp.json()
    assert data["total"] == 1
    # o resumo expõe o hash (não o dado pessoal)
    assert data["items"][0]["destinatario"] == hash_documento("98765432100")


def test_listar_nfce(client, db, empresa, api_client, auth_token):
    """GET /nfce/listar retorna apenas as notas modelo 65."""
    run(_inserir_notas(db, empresa.id, 3))  # modelo 55
    run(
        _adicionar_nota(
            db,
            _nota(
                empresa.id,
                f"{50:044d}",
                50,
                "AUTORIZADA",
                datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                modelo="65",
            ),
        )
    )

    resp = run(
        client.get(
            "/api/v1/nfce/listar",
            headers=authorization_headers(auth_token),
        )
    )

    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["modelo"] == "65"
