from decimal import Decimal

from .base import Entidade


class Produto(Entidade):
    """XXX: E provavel que esta entidade sera descartada."""

    # Dados do Produto
    # - Descricao (obrigatorio)
    descricao = ""

    # - Codigo (obrigatorio) - nao pode ser alterado quando em edicao
    codigo = ""

    # - EAN
    ean = ""

    # - EAN Unid. Tributavel
    ean_unidade_tributavel = ""

    # - EX TIPI
    ex_tipi = ""

    # - Genero
    genero = ""

    # - NCM
    ncm = ""

    # - CEST - Código especificador da substituição tributária
    # NT2015/003 http://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=uXFlhOSgUZc=
    # Tabela https://www.confaz.fazenda.gov.br/anexo-i.pdf
    cest = ""

    cbenef = ""

    # - Unid. Com.
    unidade_comercial = ""

    # - Valor Unitario Com.
    valor_unitario_comercial = Decimal()

    # - Unid. Trib.
    unidade_tributavel = ""

    # - Qtd. Trib.
    quantidade_tributavel = Decimal()

    # - Valor Unitario Trib.
    valor_unitario_tributavel = Decimal()

    # - indica se valor do item entra no valor total da nota fiscal
    # 0=Valor do item (vProd) não compõe o valor total da NF-e
    # 1=Valor do item (vProd) compõe o valor total da NF-e (vProd)
    ind_total = 0

    # # Grupo de informações de Combustível

    # Código de produto da ANP
    cProdANP = ""

    # Descrição do produto conforme ANP
    descANP = ""

    # Percentual de Gás derivado do Petróleo
    pGLP = Decimal()

    # Percentual de gás natural nacional
    pGNn = Decimal()

    # Percentual do gás natural importado
    pGNi = Decimal()

    # Valor de Partida (apenas para GLP)
    vPart = Decimal()

    # Sigla da UF de consumo – (OBS: Deve ser a Sigla e não o Código da UF)
    UFCons = ""

    # # Impostos

    # - IPI
    #  - Classe de Enquadramento (cigarros e bebidas)
    ipi_classe_enquadramento = ""

    #  - Codigo de Enquadramento Legal
    ipi_codigo_enquadramento_legal = ""

    #  - CNPJ do Produtor
    ipi_cnpj_produtor = ""

    # ICMS (Informar apenas um grupo por produto)
    """
    ICMS 00 - Tributada integralmente
    ICMS 10 - Tributada e com cobrança do ICMS por substituição tributária
    ICMS 20 - Tributada e com cobrança do ICMS por substituição tributária
    ICMS 30 - Tributação Isenta ou não tributada e com cobrança do ICMS por substituição tributária
    ICMS 30 - Isenta ou nao tributada e com cobranca do ICMS por substituicao tributaria
    ICMS 40 - Isenta
    ICMS 41 - Nao tributada
    ICMS 50 - Suspensao
    ICMS 51 - Diferimento
    ICMS 60 - Cobrado anteriormente por substituicao tributaria
    ICMS 70 - Com reducao da base de calculo e cobranca do ICMS por substituicao tributaria
    ICMS 90 - Outras
    """

    # Tributos aproximados por item
    valor_tributos_aprox = ""

    icms_modalidade = ""
    icms_origem = 0
    icms_csosn = ""
    icms_aliquota = Decimal()
    icms_credito = Decimal()

    # # PIS
    pis_modalidade = ""
    pis_valor_base_calculo = ""
    pis_aliquota_percentual = ""
    pis_valor = ""
    pis_aliquota_reais = ""

    # # COFINS
    cofins_modalidade = ""
    cofins_valor_base_calculo = ""
    cofins_aliquota_percentual = ""
    cofins_valor = ""
    cofins_aliquota_reais = ""

    # # Fundo de Combate a Pobreza
    fcp_base_calculo = Decimal()
    fcp_percentual = Decimal()
    fcp_valor = Decimal()

    # # - ICMS (lista 1 para * / ManyToManyField)
    icms = None

    def adicionar_icms(self, **kwargs):
        """Adiciona uma instancia de ICMS a lista de ICMS do produto"""
        self.icms.append(ProdutoICMS(**kwargs))

    # Informações adicionais do produto
    informacoes_adicionais = ""

    def __init__(self, *args, **kwargs):
        self.icms = []

        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} {self.descricao}"


class ProdutoICMS(Entidade):
    #  - Tipo de Tributacao (seleciona de lista) - ICMS_TIPOS_TRIBUTACAO
    tipo_tributacao = ""

    #  - Origem (seleciona de lista) - ICMS_ORIGENS
    origem = ""

    #  - Modalidade de determinacao da Base de Calculo (seleciona de lista) - ICMS_MODALIDADES
    modalidade = ""

    #  - Aliquota ICMS
    aliquota = Decimal()

    #  - Percentual de reducao da Base de Calculo
    percentual_reducao = Decimal()

    #  - Modalidade de determinacao da Base de Calculo do ICMS ST (seleciona de lista)
    #  - ICMS_ST_MODALIDADES
    st_modalidade = ""

    #  - Aliquota ICMS ST
    st_aliquota = Decimal()

    #  - Percentual de reducao do ICMS ST
    st_percentual_reducao = Decimal()

    #  - Percentual da margem de Valor Adicionado ICMS ST
    st_percentual_margem_valor_adicionado = Decimal()
