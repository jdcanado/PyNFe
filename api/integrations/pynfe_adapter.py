"""Adaptador: schemas Pydantic da API para entidades PyNFe.

Converte os schemas de `api/schemas/nota_item.py` em entidades PyNFe
(`Emitente`, `Cliente`, `NotaFiscalProduto`, `NotaFiscalPagamentos`,
`NotaFiscal`), prontas para serialização/transmissão SEFAZ.

Suporta CSTs ICMS, CSOSN Simples Nacional, PIS/COFINS, IPI e II.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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
from pynfe.entidades.cliente import Cliente
from pynfe.entidades.emitente import Emitente
from pynfe.entidades.notafiscal import (
    NotaFiscal,
    NotaFiscalPagamentos,
    NotaFiscalProduto,
)


def _dec(valor: Decimal | float | str | None) -> Decimal:
    """Converte para Decimal; None vira Decimal(0)."""
    if valor is None:
        return Decimal()
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def _sem_vazios(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove campos None ou string vazia antes de instanciar a entidade."""
    return {k: v for k, v in kwargs.items() if v is not None and v != ""}


# ---------------------------------------------------------------------------
# Emitente / Cliente
# ---------------------------------------------------------------------------


def converter_emitente(schema: EmitenteSchema) -> Emitente:
    """Converte `EmitenteSchema` em `pynfe.entidades.Emitente`."""
    return Emitente(
        razao_social=schema.razao_social,
        nome_fantasia=schema.nome_fantasia or "",
        cnpj=schema.cnpj,
        inscricao_estadual=schema.inscricao_estadual,
        cnae_fiscal=schema.cnae_fiscal or "",
        inscricao_municipal=schema.inscricao_municipal or "",
        codigo_de_regime_tributario=schema.codigo_de_regime_tributario,
        endereco_logradouro=schema.endereco_logradouro,
        endereco_numero=schema.endereco_numero,
        endereco_complemento=schema.endereco_complemento or "",
        endereco_bairro=schema.endereco_bairro,
        endereco_cep=schema.endereco_cep or "",
        endereco_uf=schema.endereco_uf,
        endereco_municipio=schema.endereco_municipio,
        endereco_cod_municipio=schema.endereco_cod_municipio or "",
        endereco_telefone=schema.endereco_telefone or "",
    )


def converter_cliente(schema: ClienteSchema) -> Cliente:
    """Converte `ClienteSchema` em `pynfe.entidades.Cliente`."""
    return Cliente(
        razao_social=schema.razao_social,
        email=schema.email or "",
        tipo_documento=schema.tipo_documento,
        numero_documento=schema.numero_documento,
        indicador_ie=schema.indicador_ie,
        inscricao_estadual=schema.inscricao_estadual or "",
        inscricao_municipal=schema.inscricao_municipal or "",
        isento_icms=schema.isento_icms,
        endereco_logradouro=schema.endereco_logradouro,
        endereco_numero=schema.endereco_numero,
        endereco_complemento=schema.endereco_complemento or "",
        endereco_bairro=schema.endereco_bairro,
        endereco_cep=schema.endereco_cep or "",
        endereco_uf=schema.endereco_uf,
        endereco_municipio=schema.endereco_municipio,
        endereco_cod_municipio=schema.endereco_cod_municipio or "",
        endereco_telefone=schema.endereco_telefone or "",
        endereco_pais=schema.endereco_pais,
    )


# ---------------------------------------------------------------------------
# Impostos (ICMS, PIS, COFINS, IPI, II)
# ---------------------------------------------------------------------------


def _icms_kwargs(icms: IcmsSchema | None) -> dict[str, Any]:
    """Gera os campos icms_* do produto a partir do `IcmsSchema`.

    `icms_modalidade`, `icms_origem` e `icms_csosn` são sempre incluídos
    (mesmo vazios) porque o serializador os acessa diretamente.
    """
    if icms is None:
        return {
            "icms_modalidade": "",
            "icms_origem": 0,
            "icms_csosn": "",
        }
    kwargs = {
        "icms_modalidade": icms.modalidade,
        "icms_origem": icms.origem,
        "icms_csosn": icms.csosn or "",
    }
    kwargs.update(
        _sem_vazios(
            {
                "icms_credito": _dec(icms.credito),
                "icms_modalidade_determinacao_bc": icms.modalidade_determinacao_bc,
                "icms_percentual_reducao_bc": _dec(icms.percentual_reducao_bc),
                "icms_valor_base_calculo": _dec(icms.valor_base_calculo),
                "icms_aliquota": _dec(icms.aliquota),
                "icms_valor": _dec(icms.valor),
                "icms_desonerado": _dec(icms.desonerado),
                "icms_motivo_desoneracao": icms.motivo_desoneracao,
                "icms_st_modalidade_determinacao_bc": icms.st_modalidade_determinacao_bc,
                "icms_st_percentual_adicional": _dec(icms.st_percentual_adicional),
                "icms_st_percentual_reducao_bc": _dec(icms.st_percentual_reducao_bc),
                "icms_st_valor_base_calculo": _dec(icms.st_valor_base_calculo),
                "icms_st_aliquota": _dec(icms.st_aliquota),
                "icms_st_valor": _dec(icms.st_valor),
                "fcp_base_calculo": _dec(icms.fcp_base_calculo),
                "fcp_aliquota": _dec(icms.fcp_aliquota),
                "fcp_valor": _dec(icms.fcp_valor),
            }
        )
    )
    return kwargs


def _pis_kwargs(pis: PisSchema | None) -> dict[str, Any]:
    """Gera os campos pis_* do produto a partir do `PisSchema`."""
    if pis is None:
        return {}
    return _sem_vazios(
        {
            "pis_modalidade": pis.situacao_tributaria,
            "pis_tipo_calculo": pis.tipo_calculo,
            "pis_valor_base_calculo": _dec(pis.valor_base_calculo),
            "pis_aliquota_percentual": _dec(pis.aliquota_percentual),
            "pis_aliquota_reais": _dec(pis.aliquota_reais),
            "pis_quantidade_vendida": _dec(pis.quantidade_vendida),
            "pis_valor": _dec(pis.valor),
        }
    )


def _cofins_kwargs(cofins: CofinsSchema | None) -> dict[str, Any]:
    """Gera os campos cofins_* do produto a partir do `CofinsSchema`."""
    if cofins is None:
        return {}
    return _sem_vazios(
        {
            "cofins_modalidade": cofins.situacao_tributaria,
            "cofins_tipo_calculo": cofins.tipo_calculo,
            "cofins_valor_base_calculo": _dec(cofins.valor_base_calculo),
            "cofins_aliquota_percentual": _dec(cofins.aliquota_percentual),
            "cofins_aliquota_reais": _dec(cofins.aliquota_reais),
            "cofins_quantidade_vendida": _dec(cofins.quantidade_vendida),
            "cofins_valor": _dec(cofins.valor),
        }
    )


def _ipi_kwargs(ipi: IpiSchema | None) -> dict[str, Any]:
    """Gera os campos ipi_* do produto a partir do `IpiSchema`."""
    if ipi is None:
        return {}
    return _sem_vazios(
        {
            "ipi_situacao_tributaria": ipi.situacao_tributaria,
            "ipi_tipo_calculo": ipi.tipo_calculo,
            "ipi_classe_enquadramento": ipi.classe_enquadramento,
            "ipi_codigo_enquadramento": ipi.codigo_enquadramento,
            "ipi_valor_base_calculo": _dec(ipi.valor_base_calculo),
            "ipi_aliquota": _dec(ipi.aliquota),
            "ipi_quantidade_total_unidade_padrao": _dec(ipi.quantidade_total_unidade_padrao),
            "ipi_valor_unidade": _dec(ipi.valor_unidade),
            "ipi_valor_ipi": _dec(ipi.valor_ipi),
        }
    )


def _ii_kwargs(ii: ImpostoImportacaoSchema | None) -> dict[str, Any]:
    """Gera os campos de imposto de importação do produto."""
    if ii is None:
        return {}
    return _sem_vazios(
        {
            "imposto_importacao_valor_base_calculo": _dec(ii.valor_base_calculo),
            "imposto_importacao_valor_despesas_aduaneiras": _dec(ii.valor_despesas_aduaneiras),
            "imposto_importacao_valor_iof": _dec(ii.valor_iof),
            "imposto_importacao_valor": _dec(ii.valor),
        }
    )


# ---------------------------------------------------------------------------
# Produto / Pagamento
# ---------------------------------------------------------------------------


def converter_produto_kwargs(schema: ProdutoItemSchema) -> dict[str, Any]:
    """Gera os kwargs do produto (dados + impostos) para `NotaFiscalProduto`."""
    kwargs = _sem_vazios(
        {
            "codigo": schema.codigo,
            "descricao": schema.descricao,
            "ncm": schema.ncm,
            "cfop": schema.cfop,
            "ean": schema.ean,
            "ean_tributavel": schema.ean_tributavel,
            "cest": schema.cest,
            "unidade_comercial": schema.unidade_comercial,
            "quantidade_comercial": _dec(schema.quantidade_comercial),
            "valor_unitario_comercial": _dec(schema.valor_unitario_comercial),
            "unidade_tributavel": schema.unidade_tributavel or schema.unidade_comercial,
            "quantidade_tributavel": _dec(schema.quantidade_tributavel)
            if schema.quantidade_tributavel is not None
            else _dec(schema.quantidade_comercial),
            "valor_unitario_tributavel": _dec(schema.valor_unitario_tributavel)
            if schema.valor_unitario_tributavel is not None
            else _dec(schema.valor_unitario_comercial),
            "valor_total_bruto": _dec(schema.valor_total_bruto),
            "desconto": _dec(schema.desconto),
            "total_frete": _dec(schema.total_frete),
            "total_seguro": _dec(schema.total_seguro),
            "outras_despesas_acessorias": _dec(schema.outras_despesas_acessorias),
            "numero_pedido": schema.numero_pedido,
            "numero_item": schema.numero_item,
            "informacoes_adicionais": schema.informacoes_adicionais,
            "ind_total": schema.ind_total,
        }
    )
    # Atributo acessado pelo serializador; sempre presente (mesmo vazio)
    kwargs["valor_tributos_aprox"] = ""
    kwargs.update(_icms_kwargs(schema.icms))
    kwargs.update(_pis_kwargs(schema.pis))
    kwargs.update(_cofins_kwargs(schema.cofins))
    kwargs.update(_ipi_kwargs(schema.ipi))
    kwargs.update(_ii_kwargs(schema.ii))
    return kwargs


def converter_produto(schema: ProdutoItemSchema) -> NotaFiscalProduto:
    """Converte `ProdutoItemSchema` em `NotaFiscalProduto` (com impostos)."""
    return NotaFiscalProduto(**converter_produto_kwargs(schema))


def converter_pagamento_kwargs(schema: PagamentoSchema) -> dict[str, Any]:
    """Gera os kwargs do pagamento para `NotaFiscalPagamentos`."""
    return {
        "t_pag": schema.forma_pagamento,
        "x_pag": schema.descricao or "",
        "v_pag": _dec(schema.valor),
        "tp_integra": schema.tipo_integracao or "",
        "ind_pag": schema.indicador_forma_pagamento,
    }


def converter_pagamento(schema: PagamentoSchema) -> NotaFiscalPagamentos:
    """Converte `PagamentoSchema` em `NotaFiscalPagamentos`."""
    return NotaFiscalPagamentos(**converter_pagamento_kwargs(schema))


# ---------------------------------------------------------------------------
# Nota Fiscal
# ---------------------------------------------------------------------------


def converter_nota_fiscal(schema: NotaFiscalSchema) -> NotaFiscal:
    """Converte `NotaFiscalSchema` em `NotaFiscal` completa (PyNFe).

    Monta emitente/destinatário, adiciona produtos (com impostos) e
    pagamentos. A entidade resultante pode ser serializada pelo PyNFe.
    """
    nota = NotaFiscal(
        emitente=converter_emitente(schema.emitente),
        cliente=converter_cliente(schema.cliente),
        uf=schema.uf,
        municipio=schema.municipio,
        natureza_operacao=schema.natureza_operacao,
        tipo_documento=schema.tipo_documento,
        data_emissao=schema.data_emissao or datetime.now(timezone.utc),
        data_saida_entrada=schema.data_saida_entrada,
        modelo=schema.modelo,
        serie=str(schema.serie),
        numero_nf=str(schema.numero),
        forma_emissao=str(schema.forma_emissao),
        finalidade_emissao=str(schema.finalidade_emissao),
        # Indicadores obrigatórios do grupo ide (defaults válidos no schema)
        indicador_destino=schema.indicador_destino,
        tipo_impressao_danfe=schema.tipo_impressao_danfe,
        indicador_presencial=schema.indicador_presencial,
        cliente_final=schema.cliente_final,
    )

    for produto in schema.produtos:
        nota.adicionar_produto_servico(**converter_produto_kwargs(produto))

    for pagamento in schema.pagamentos:
        nota.adicionar_pagamento(**converter_pagamento_kwargs(pagamento))

    return nota
