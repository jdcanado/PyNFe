"""Testes do adapter PyNFe (schemas Pydantic -> entidades PyNFe)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.integrations.pynfe_adapter import (
    converter_cliente,
    converter_emitente,
    converter_nota_fiscal,
    converter_pagamento,
    converter_produto,
)
from api.schemas.nota_item import (
    ClienteSchema,
    CofinsSchema,
    EmitenteSchema,
    IcmsSchema,
    ImpostoImportacaoSchema,
    IpiSchema,
    NotaFiscalSchema,
    PagamentoSchema,
    PisSchema,
    ProdutoItemSchema,
)

EMITENTE = EmitenteSchema(
    razao_social="Empresa Teste LTDA",
    cnpj="99999999000199",
    inscricao_estadual="9999999999",
    codigo_de_regime_tributario="3",
    endereco_logradouro="Rua da Paz",
    endereco_numero="666",
    endereco_bairro="Sossego",
    endereco_uf="PR",
    endereco_municipio="Paranavaí",
    endereco_cod_municipio="4118402",
    endereco_cep="87704000",
)

CLIENTE = ClienteSchema(
    razao_social="JOSE DA SILVA",
    tipo_documento="CPF",
    numero_documento="12345678900",
    indicador_ie=9,
    endereco_logradouro="Rua dos Bobos",
    endereco_numero="Zero",
    endereco_bairro="Aquele Mesmo",
    endereco_uf="DF",
    endereco_municipio="Brasilia",
    endereco_cep="12345123",
)


def produto_schema(**icms_kwargs) -> ProdutoItemSchema:
    """Monta um `ProdutoItemSchema` com impostos padrão."""
    return ProdutoItemSchema(
        codigo="000328",
        descricao="Produto teste",
        ncm="99999999",
        cfop="5102",
        ean="1234567890121",
        unidade_comercial="UN",
        quantidade_comercial=Decimal(12),
        valor_unitario_comercial=Decimal("9.75"),
        valor_total_bruto=Decimal("117.00"),
        icms=IcmsSchema(**{"modalidade": "00", "origem": 0, **icms_kwargs}),
        pis=PisSchema(
            situacao_tributaria="01",
            valor_base_calculo=Decimal("117.00"),
            aliquota_percentual=Decimal("0.65"),
            valor=Decimal("0.76"),
        ),
        cofins=CofinsSchema(
            situacao_tributaria="01",
            valor_base_calculo=Decimal("117.00"),
            aliquota_percentual=Decimal("3.00"),
            valor=Decimal("3.51"),
        ),
    )


def nota_schema(**overrides) -> NotaFiscalSchema:
    """Monta um `NotaFiscalSchema` completo."""
    data = {
        "empresa_id": "00000000-0000-0000-0000-000000000001",
        "uf": "PR",
        "municipio": "4118402",
        "natureza_operacao": "VENDA",
        "tipo_documento": 1,
        "data_emissao": datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        "modelo": 55,
        "serie": "1",
        "numero": "111",
        "finalidade_emissao": "1",
        "emitente": EMITENTE,
        "cliente": CLIENTE,
        "produtos": [produto_schema()],
        "pagamentos": [PagamentoSchema(forma_pagamento="01", valor=Decimal("117.00"))],
    }
    data.update(overrides)
    return NotaFiscalSchema(**data)


# ---------------------------------------------------------------------------
# Schemas: validações de formato
# ---------------------------------------------------------------------------


def test_emitente_cnpj_invalido():
    with pytest.raises(ValidationError):
        EmitenteSchema(
            razao_social="X",
            cnpj="123",
            endereco_logradouro="R",
            endereco_numero="1",
            endereco_bairro="B",
            endereco_uf="PR",
            endereco_municipio="M",
        )


def test_uf_normaliza_para_maiusculas():
    schema = ClienteSchema(
        razao_social="X",
        numero_documento="123",
        endereco_logradouro="R",
        endereco_numero="1",
        endereco_bairro="B",
        endereco_uf="sp",
        endereco_municipio="M",
    )
    assert schema.endereco_uf == "SP"


# ---------------------------------------------------------------------------
# Emitente / Cliente
# ---------------------------------------------------------------------------


def test_converter_emitente():
    emitente = converter_emitente(EMITENTE)
    assert emitente.razao_social == "Empresa Teste LTDA"
    assert emitente.cnpj == "99999999000199"
    assert emitente.inscricao_estadual == "9999999999"
    assert emitente.codigo_de_regime_tributario == "3"
    assert emitente.endereco_uf == "PR"
    assert emitente.endereco_municipio == "Paranavaí"


def test_converter_cliente():
    cliente = converter_cliente(CLIENTE)
    assert cliente.razao_social == "JOSE DA SILVA"
    assert cliente.tipo_documento == "CPF"
    assert cliente.numero_documento == "12345678900"
    assert cliente.indicador_ie == 9
    assert cliente.endereco_uf == "DF"


# ---------------------------------------------------------------------------
# Produto com impostos
# ---------------------------------------------------------------------------


def test_converter_produto_dados_basicos():
    produto = converter_produto(produto_schema())
    assert produto.codigo == "000328"
    assert produto.descricao == "Produto teste"
    assert produto.ncm == "99999999"
    assert produto.cfop == "5102"
    assert produto.quantidade_comercial == Decimal(12)
    assert produto.valor_unitario_comercial == Decimal("9.75")
    assert produto.valor_total_bruto == Decimal("117.00")
    assert produto.unidade_tributavel == "UN"


def test_converter_produto_icms_cst00():
    produto = converter_produto(
        produto_schema(
            valor_base_calculo=Decimal("117.00"),
            aliquota=Decimal("18.00"),
            valor=Decimal("21.06"),
        )
    )
    assert produto.icms_modalidade == "00"
    assert produto.icms_origem == 0
    assert produto.icms_csosn == ""
    assert produto.icms_valor_base_calculo == Decimal("117.00")
    assert produto.icms_aliquota == Decimal("18.00")
    assert produto.icms_valor == Decimal("21.06")


def test_converter_produto_icms_csosn101():
    produto = converter_produto(
        produto_schema(
            modalidade="101",
            csosn="101",
            credito=Decimal("3.51"),
        )
    )
    assert produto.icms_modalidade == "101"
    assert produto.icms_csosn == "101"
    assert produto.icms_credito == Decimal("3.51")


def test_converter_produto_icms_st():
    produto = converter_produto(
        produto_schema(
            st_modalidade_determinacao_bc=4,
            st_percentual_adicional=Decimal("40.00"),
            st_valor_base_calculo=Decimal("117.00"),
            st_aliquota=Decimal("18.00"),
            st_valor=Decimal("21.06"),
        )
    )
    assert produto.icms_st_modalidade_determinacao_bc == 4
    assert produto.icms_st_percentual_adicional == Decimal("40.00")
    assert produto.icms_st_valor_base_calculo == Decimal("117.00")
    assert produto.icms_st_valor == Decimal("21.06")


def test_converter_produto_pis_cofins():
    produto = converter_produto(produto_schema())
    assert produto.pis_modalidade == "01"
    assert produto.pis_valor_base_calculo == Decimal("117.00")
    assert produto.pis_aliquota_percentual == Decimal("0.65")
    assert produto.pis_valor == Decimal("0.76")
    assert produto.cofins_modalidade == "01"
    assert produto.cofins_valor_base_calculo == Decimal("117.00")
    assert produto.cofins_aliquota_percentual == Decimal("3.00")
    assert produto.cofins_valor == Decimal("3.51")


def test_converter_produto_ipi():
    schema = produto_schema()
    schema.ipi = IpiSchema(
        situacao_tributaria="50",
        tipo_calculo="1",
        valor_base_calculo=Decimal("117.00"),
        aliquota=Decimal("5.00"),
        valor_ipi=Decimal("5.85"),
    )
    produto = converter_produto(schema)
    assert produto.ipi_situacao_tributaria == "50"
    assert produto.ipi_valor_base_calculo == Decimal("117.00")
    assert produto.ipi_aliquota == Decimal("5.00")
    assert produto.ipi_valor_ipi == Decimal("5.85")


def test_converter_produto_ii_importacao():
    schema = produto_schema()
    schema.ii = ImpostoImportacaoSchema(
        valor_base_calculo=Decimal("100.00"),
        valor_despesas_aduaneiras=Decimal("10.00"),
        valor_iof=Decimal("5.00"),
        valor=Decimal("20.00"),
    )
    produto = converter_produto(schema)
    assert produto.imposto_importacao_valor_base_calculo == Decimal("100.00")
    assert produto.imposto_importacao_valor_despesas_aduaneiras == Decimal("10.00")
    assert produto.imposto_importacao_valor_iof == Decimal("5.00")
    assert produto.imposto_importacao_valor == Decimal("20.00")


def test_converter_produto_sem_impostos():
    schema = produto_schema()
    schema.icms = None
    schema.pis = None
    schema.cofins = None
    produto = converter_produto(schema)
    assert produto.icms_modalidade == ""
    assert produto.pis_valor == Decimal()


# ---------------------------------------------------------------------------
# Pagamento
# ---------------------------------------------------------------------------


def test_converter_pagamento():
    pagamento = converter_pagamento(
        PagamentoSchema(forma_pagamento="03", valor=Decimal("117.00"), descricao="Credito")
    )
    assert pagamento.t_pag == "03"
    assert pagamento.v_pag == Decimal("117.00")
    assert pagamento.x_pag == "Credito"
    assert pagamento.ind_pag == 0


# ---------------------------------------------------------------------------
# Nota fiscal completa
# ---------------------------------------------------------------------------


def test_converter_nota_fiscal_completa():
    nota = converter_nota_fiscal(nota_schema())

    assert nota.uf == "PR"
    assert nota.municipio == "4118402"
    assert nota.natureza_operacao == "VENDA"
    assert nota.tipo_documento == 1
    assert nota.modelo == 55
    assert nota.serie == "1"
    assert nota.numero_nf == "111"
    assert nota.finalidade_emissao == "1"
    assert nota.emitente.cnpj == "99999999000199"
    assert nota.cliente.numero_documento == "12345678900"

    # Produtos adicionados e totais acumulados
    assert len(nota.produtos_e_servicos) == 1
    produto = nota.produtos_e_servicos[0]
    assert produto.icms_modalidade == "00"
    assert nota.totais_icms_total_produtos_e_servicos == Decimal("117.00")
    assert nota.totais_icms_pis == Decimal("0.76")
    assert nota.totais_icms_cofins == Decimal("3.51")

    # Pagamentos adicionados
    assert len(nota.pagamentos) == 1
    assert nota.pagamentos[0].t_pag == "01"
    assert nota.pagamentos[0].v_pag == Decimal("117.00")


def test_converter_nota_fiscal_com_icms_e_ipi_ii():
    schema = nota_schema()
    schema.produtos[0].icms = IcmsSchema(
        modalidade="00",
        origem=0,
        valor_base_calculo=Decimal("117.00"),
        aliquota=Decimal("18.00"),
        valor=Decimal("21.06"),
    )
    schema.produtos[0].ipi = IpiSchema(
        situacao_tributaria="50",
        valor_base_calculo=Decimal("117.00"),
        aliquota=Decimal("5.00"),
        valor_ipi=Decimal("5.85"),
    )
    schema.produtos[0].ii = ImpostoImportacaoSchema(
        valor_base_calculo=Decimal("100.00"),
        valor=Decimal("20.00"),
    )

    nota = converter_nota_fiscal(schema)
    produto = nota.produtos_e_servicos[0]

    assert produto.icms_valor == Decimal("21.06")
    assert produto.ipi_valor_ipi == Decimal("5.85")
    assert produto.imposto_importacao_valor == Decimal("20.00")
    # totais_icms_total acumula II + IPI no vNF
    assert nota.totais_icms_total_ii == Decimal("20.00")
    assert nota.totais_icms_total_ipi == Decimal("5.85")


# ---------------------------------------------------------------------------
# Indicadores do grupo ide (idDest/tpImp/indPres/indFinal)
# ---------------------------------------------------------------------------


def test_nota_schema_indicadores_defaults_validos():
    schema = nota_schema()
    assert schema.indicador_destino == 1  # operação interna
    assert schema.tipo_impressao_danfe == 1  # DANFE normal
    assert schema.indicador_presencial == 0  # não se aplica
    assert schema.cliente_final == 0  # não consumidor final


def test_nota_schema_indicadores_invalidos_rejeitados():
    with pytest.raises(ValidationError):
        nota_schema(indicador_destino=0)  # idDest só aceita 1-3
    with pytest.raises(ValidationError):
        nota_schema(tipo_impressao_danfe=0)  # tpImp só aceita 1-5
    with pytest.raises(ValidationError):
        nota_schema(cliente_final=2)  # indFinal só aceita 0-1


def test_converter_nota_fiscal_propaga_indicadores():
    schema = nota_schema(
        indicador_destino=2,
        tipo_impressao_danfe=1,
        indicador_presencial=2,
        cliente_final=1,
    )
    nota = converter_nota_fiscal(schema)
    assert nota.indicador_destino == 2
    assert nota.tipo_impressao_danfe == 1
    assert nota.indicador_presencial == 2
    assert nota.cliente_final == 1
