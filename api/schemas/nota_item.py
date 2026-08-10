"""Schemas Pydantic para o payload de emissão de NF-e (itens, impostos, partes).

Usados pelo `api/integrations/pynfe_adapter.py` para converter em entidades
PyNFe. Validações de formato (CNPJ 14 dígitos, UF 2 letras) são locais para
manter o módulo independente.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _validar_cnpj(v: str) -> str:
    if not v.isdigit() or len(v) != 14:
        raise ValueError("CNPJ deve ter exatamente 14 dígitos numéricos")
    return v


def _validar_uf(v: str) -> str:
    if len(v) != 2 or not v.isalpha():
        raise ValueError("UF deve ter exatamente 2 letras")
    return v.upper()


class EmitenteSchema(BaseModel):
    """Emitente da nota (dados cadastrais + endereço)."""

    razao_social: str = Field(min_length=1, max_length=200)
    cnpj: str
    inscricao_estadual: str = ""
    nome_fantasia: str | None = None
    cnae_fiscal: str | None = None
    inscricao_municipal: str | None = None
    codigo_de_regime_tributario: str = ""
    endereco_logradouro: str
    endereco_numero: str
    endereco_complemento: str | None = None
    endereco_bairro: str
    endereco_cep: str | None = None
    endereco_uf: str
    endereco_municipio: str
    endereco_cod_municipio: str | None = None
    endereco_telefone: str | None = None

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str) -> str:
        return _validar_cnpj(v)

    @field_validator("endereco_uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        return _validar_uf(v)


class ClienteSchema(BaseModel):
    """Destinatário/remetente da nota."""

    razao_social: str = Field(min_length=1, max_length=200)
    tipo_documento: str = "CNPJ"
    numero_documento: str
    email: str | None = None
    indicador_ie: int = Field(default=9, ge=0, le=9)
    inscricao_estadual: str | None = None
    inscricao_municipal: str | None = None
    isento_icms: bool = False
    endereco_logradouro: str
    endereco_numero: str
    endereco_complemento: str | None = None
    endereco_bairro: str
    endereco_cep: str | None = None
    endereco_uf: str
    endereco_municipio: str
    endereco_cod_municipio: str | None = None
    endereco_telefone: str | None = None
    endereco_pais: str = Field(default="1058", description="cPais do destinatário (1058 = Brasil)")

    @field_validator("endereco_uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        return _validar_uf(v)


class IcmsSchema(BaseModel):
    """Grupo ICMS de um item (CST normal ou CSOSN Simples Nacional)."""

    modalidade: str = Field(description="CST (00-90) ou CSOSN (101-900)")
    origem: int = 0
    csosn: str | None = None
    credito: Decimal | None = None
    modalidade_determinacao_bc: int = 0
    percentual_reducao_bc: Decimal | None = None
    valor_base_calculo: Decimal | None = None
    aliquota: Decimal | None = None
    valor: Decimal | None = None
    desonerado: Decimal | None = None
    motivo_desoneracao: int = 0
    # ICMS ST
    st_modalidade_determinacao_bc: int = 0
    st_percentual_adicional: Decimal | None = None
    st_percentual_reducao_bc: Decimal | None = None
    st_valor_base_calculo: Decimal | None = None
    st_aliquota: Decimal | None = None
    st_valor: Decimal | None = None
    # FCP
    fcp_base_calculo: Decimal | None = None
    fcp_aliquota: Decimal | None = None
    fcp_valor: Decimal | None = None


class PisSchema(BaseModel):
    """Grupo PIS de um item."""

    situacao_tributaria: str = Field(default="99", description="CST PIS (01-99)")
    tipo_calculo: str | None = None
    valor_base_calculo: Decimal | None = None
    aliquota_percentual: Decimal | None = None
    aliquota_reais: Decimal | None = None
    quantidade_vendida: Decimal | None = None
    valor: Decimal | None = None


class CofinsSchema(BaseModel):
    """Grupo COFINS de um item."""

    situacao_tributaria: str = Field(default="99", description="CST COFINS (01-99)")
    tipo_calculo: str | None = None
    valor_base_calculo: Decimal | None = None
    aliquota_percentual: Decimal | None = None
    aliquota_reais: Decimal | None = None
    quantidade_vendida: Decimal | None = None
    valor: Decimal | None = None


class IpiSchema(BaseModel):
    """Grupo IPI de um item."""

    situacao_tributaria: str = Field(default="99", description="CST IPI (00-99)")
    tipo_calculo: str | None = None
    classe_enquadramento: str | None = None
    codigo_enquadramento: str | None = None
    valor_base_calculo: Decimal | None = None
    aliquota: Decimal | None = None
    quantidade_total_unidade_padrao: Decimal | None = None
    valor_unidade: Decimal | None = None
    valor_ipi: Decimal | None = None


class ImpostoImportacaoSchema(BaseModel):
    """Grupo II (imposto de importação) de um item."""

    valor_base_calculo: Decimal | None = None
    valor_despesas_aduaneiras: Decimal | None = None
    valor_iof: Decimal | None = None
    valor: Decimal | None = None


class ProdutoItemSchema(BaseModel):
    """Item (produto/serviço) de uma nota, com seus impostos."""

    codigo: str
    descricao: str
    ncm: str
    cfop: str
    ean: str = "SEM GTIN"
    ean_tributavel: str = "SEM GTIN"
    unidade_comercial: str
    quantidade_comercial: Decimal
    valor_unitario_comercial: Decimal
    unidade_tributavel: str | None = None
    quantidade_tributavel: Decimal | None = None
    valor_unitario_tributavel: Decimal | None = None
    valor_total_bruto: Decimal
    cest: str | None = None
    desconto: Decimal | None = None
    total_frete: Decimal | None = None
    total_seguro: Decimal | None = None
    outras_despesas_acessorias: Decimal | None = None
    numero_pedido: str | None = None
    numero_item: str | None = None
    informacoes_adicionais: str | None = None
    ind_total: int = 1

    icms: IcmsSchema | None = None
    pis: PisSchema | None = None
    cofins: CofinsSchema | None = None
    ipi: IpiSchema | None = None
    ii: ImpostoImportacaoSchema | None = None


class PagamentoSchema(BaseModel):
    """Forma de pagamento da nota (grupo pag)."""

    forma_pagamento: str = Field(default="01", description="tPag: 01=Dinheiro, 03=Crédito, ...")
    valor: Decimal
    descricao: str | None = None
    tipo_integracao: str | None = None
    indicador_forma_pagamento: int = Field(default=0, ge=0, le=1)


class NotaFiscalSchema(BaseModel):
    """Payload completo de emissão de NF-e/NFC-e."""

    empresa_id: UUID
    uf: str
    municipio: str
    natureza_operacao: str
    tipo_documento: int = 1  # 0=entrada; 1=saida
    data_emissao: datetime | None = None
    data_saida_entrada: datetime | None = None
    modelo: int = 55  # 55=NF-e; 65=NFC-e
    serie: str = "1"
    numero: str
    forma_emissao: str = "1"  # 1=Emissão normal (não em contingência)
    finalidade_emissao: str = "1"  # 1=NF-e normal
    # -- Indicadores obrigatórios no XML (defaults válidos p/ operação interna) --
    indicador_destino: int = Field(
        default=1, ge=1, le=3, description="idDest: 1=interna; 2=interestadual; 3=exterior"
    )
    tipo_impressao_danfe: int = Field(
        default=1,
        ge=1,
        le=5,
        description="tpImp: 1=DANFE normal; 4=NFC-e; 5=DANFE NFC-e mensagem eletrônica",
    )
    indicador_presencial: int = Field(
        default=0,
        ge=0,
        le=5,
        description="indPres: 0=não se aplica; 1=presencial; 2=internet; 3=teleatendimento",
    )
    cliente_final: int = Field(
        default=0, ge=0, le=1, description="indFinal: 0=normal; 1=consumidor final"
    )

    emitente: EmitenteSchema
    cliente: ClienteSchema
    produtos: list[ProdutoItemSchema] = Field(default_factory=list)
    pagamentos: list[PagamentoSchema] = Field(default_factory=list)

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        return _validar_uf(v)
