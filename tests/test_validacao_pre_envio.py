"""Testes das validações pré-envio que espelham rejeições da SEFAZ."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from api.core.exceptions import ValidacaoNegocioError
from api.schemas.nfce import NFCeEmitirRequest
from api.schemas.nota_item import (
    CofinsSchema,
    EmitenteSchema,
    IBSCBSSchema,
    IcmsSchema,
    PagamentoSchema,
    PisSchema,
    ProdutoItemSchema,
)
from api.services.validacao_pre_envio import (
    DESCRICAO_HOMOLOGACAO,
    aplicar_descricao_homologacao,
    validar_nfce,
)

EMITENTE = EmitenteSchema(
    razao_social="Empresa Teste LTDA",
    cnpj="99999999000199",
    inscricao_estadual="9999999999",
    codigo_de_regime_tributario="1",
    endereco_logradouro="Rua da Paz",
    endereco_numero="666",
    endereco_bairro="Sossego",
    endereco_uf="PR",
    endereco_municipio="Paranavaí",
    endereco_cod_municipio="4118402",
    endereco_cep="87704000",
)


def produto(**icms_kwargs) -> ProdutoItemSchema:
    """Produto válido (NCM/GTIN reais, CSOSN Simples por padrão)."""
    return ProdutoItemSchema(
        codigo="000328",
        descricao="Produto teste",
        ncm="61091000",
        cfop="5102",
        ean="1234567890128",
        unidade_comercial="UN",
        quantidade_comercial=Decimal(1),
        valor_unitario_comercial=Decimal("10.00"),
        valor_total_bruto=Decimal("10.00"),
        icms=IcmsSchema(**{"modalidade": "102", "csosn": "102", "origem": 0, **icms_kwargs}),
        pis=PisSchema(situacao_tributaria="49"),
        cofins=CofinsSchema(situacao_tributaria="49"),
        ibscbs=IBSCBSSchema(cst="000", c_class_trib="000001"),
    )


def schema_nfce(
    *,
    item: ProdutoItemSchema | None = None,
    data_emissao: datetime | None = None,
    crt_emitente: str = "1",
) -> NFCeEmitirRequest:
    """Monta um NFCeEmitirRequest mínimo para as validações."""
    return NFCeEmitirRequest(
        empresa_id=uuid4(),
        uf="PR",
        municipio="4118402",
        natureza_operacao="VENDA",
        data_emissao=data_emissao,
        serie="1",
        numero="1",
        indicador_presencial=1,
        tipo_impressao_danfe=4,
        emitente=EMITENTE.model_copy(update={"codigo_de_regime_tributario": crt_emitente}),
        cliente=None,
        produtos=[item or produto()],
        pagamentos=[PagamentoSchema(forma_pagamento="01", valor=Decimal("10.00"))],
    )


# ---------------------------------------------------------------------------
# 704 — data de emissão retroativa
# ---------------------------------------------------------------------------


def test_704_data_retroativa_levanta_erro():
    schema = schema_nfce(data_emissao=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValidacaoNegocioError, match="704"):
        validar_nfce(schema)


def test_704_sem_data_emissao_ok():
    """Sem data_emissao no payload não bloqueia (o serviço usa a data atual)."""
    validar_nfce(schema_nfce(data_emissao=None))


def test_704_data_hoje_ok():
    validar_nfce(schema_nfce(data_emissao=datetime.now(timezone.utc)))


# ---------------------------------------------------------------------------
# 590 — CST vs CSOSN conforme o CRT
# ---------------------------------------------------------------------------


def test_590_crt1_com_cst_levanta_erro():
    schema = schema_nfce(item=produto(modalidade="00", csosn=None))
    with pytest.raises(ValidacaoNegocioError, match="590"):
        validar_nfce(schema, crt="1")


def test_590_crt1_com_csosn_sem_campo_csosn_levanta_erro():
    schema = schema_nfce(item=produto(modalidade="102", csosn=None))
    with pytest.raises(ValidacaoNegocioError, match="590"):
        validar_nfce(schema, crt="1")


def test_590_crt1_com_csosn_valido_ok():
    validar_nfce(schema_nfce(), crt="1")  # produto padrão: CSOSN 102 + csosn=102


def test_590_crt3_com_csosn_levanta_erro():
    schema = schema_nfce(item=produto(modalidade="102", csosn="102"))
    with pytest.raises(ValidacaoNegocioError, match="CRT=3"):
        validar_nfce(schema, crt="3")


def test_590_sem_crt_nao_bloqueia():
    """CRT ausente (nem cadastro nem payload): validação de regime não bloqueia."""
    validar_nfce(schema_nfce(), crt=None)


# ---------------------------------------------------------------------------
# 1115 — IBS/CBS obrigatório no item
# ---------------------------------------------------------------------------


def test_1115_item_sem_ibscbs_levanta_erro():
    item_sem_ibscbs = produto()
    item_sem_ibscbs.ibscbs = None
    schema = schema_nfce(item=item_sem_ibscbs)
    with pytest.raises(ValidacaoNegocioError, match="1115"):
        validar_nfce(schema)


def test_1115_com_ibscbs_ok():
    validar_nfce(schema_nfce())


# ---------------------------------------------------------------------------
# 373 — descrição do 1º item em homologação
# ---------------------------------------------------------------------------


def test_373_substitui_descricao_em_homologacao():
    schema = schema_nfce()
    alterado = aplicar_descricao_homologacao(schema, homologacao=True)
    assert alterado is True
    assert schema.produtos[0].descricao == DESCRICAO_HOMOLOGACAO


def test_373_nao_altera_em_producao():
    schema = schema_nfce()
    assert aplicar_descricao_homologacao(schema, homologacao=False) is False
    assert schema.produtos[0].descricao == "Produto teste"
