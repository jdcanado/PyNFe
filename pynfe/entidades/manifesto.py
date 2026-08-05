import random
from decimal import Decimal

from pynfe import get_version
from pynfe.utils import so_numeros
from pynfe.utils.flags import CODIGOS_ESTADOS, MDFE_STATUS

from .base import Entidade


class Manifesto(Entidade):
    status = MDFE_STATUS[0]

    # - UF - converter para codigos em CODIGOS_ESTADOS
    uf = ""

    # tpAmb

    # - Tipo Emitente
    # 1=Transportadora; 2=Carga própria; 3=CTe Globalizado
    tipo_emitente = 0

    # - Tipo transportador - 0=nenhum; 1=etc; 2=tac; 3=ctc
    tipo_transportador = 0

    # Manifesto fixo 58
    # - Modelo (formato: NN)
    modelo = 58

    # - Serie (obrigatorio - formato: NNN)
    serie = ""

    # - Numero MDFe (obrigatorio)
    numero_mdfe = ""

    # - Código numérico aleatório que compõe a chave de acesso
    codigo_numerico_aleatorio = ""

    # - Digito verificador do codigo numerico aleatorio
    dv_codigo_numerico_aleatorio = ""

    # - Tipo do modal de transporte
    # 1=Rodoviario; 2=Aereo; 3=Aquaviario; 4=Ferroviario
    modal = 1

    # - Data da Emissao (obrigatorio)
    data_emissao = None

    # - Forma de emissao (obrigatorio - seleciona de lista) - NF_FORMAS_EMISSAO
    forma_emissao = ""

    # - Processo de emissão da NF-e (obrigatorio - seleciona de lista) - NF_PROCESSOS_EMISSAO
    processo_emissao = 0

    # - Versao do processo de emissão do MDF-e
    versao_processo_emissao = get_version()

    # - UF inicio. Exemplo SP, MT, PR
    UFIni = ""

    # - UF final. Exemplo SP, MT, PR
    UFFim = ""

    # - Digest value da NF-e (somente leitura)
    digest_value = None

    # - Protocolo (somente leitura)
    protocolo = ""

    # - Data (somente leitura)
    data = None

    # - Municípios carregamento (lista 1 para * / ManyToManyField)
    municipio_carrega = None

    # - Percurso da viagem (lista 1 para * / ManyToManyField)
    percurso = None

    # Data inicial da viagem
    dhIniViagem = None

    # - Emitente (lista 1 para * / ManyToManyField)
    emitente = None

    # - Modal rodoviario (lista 1 para * / ManyToManyField)
    modal_rodoviario = None

    # - Documentos vinculados NFe ou CTe (lista 1 para * / ManyToManyField)
    documentos = None

    # - Seguradora (lista 1 para * / ManyToManyField)
    seguradora = None

    # - Produto predominante
    produto = None

    # - Resumo dos Totais do MDF-e
    totais = None

    # - Lacres
    lacres = None

    # - Informacoes Adicionais
    #  - Informacoes adicionais de interesse do fisco
    informacoes_adicionais_interesse_fisco = ""

    #  - Informacoes complementares de interesse do contribuinte
    informacoes_complementares_interesse_contribuinte = ""

    def __init__(self, *args, **kwargs):
        self.municipio_carrega = []
        self.percurso = []
        self.modal_rodoviario = []
        self.documentos = []
        self.seguradora = []
        self.produto = []
        self.lacres = []
        self.responsavel_tecnico = []
        super().__init__(*args, **kwargs)

    def __str__(self):
        return " ".join([str(self.modelo), self.serie, self.numero_mdfe])

    def adicionar_municipio_carrega(self, **kwargs):
        obj = ManifestoMunicipioCarrega(**kwargs)
        self.municipio_carrega.append(obj)
        return obj

    def adicionar_percurso(self, **kwargs):
        obj = ManifestoPercurso(**kwargs)
        self.percurso.append(obj)
        return obj

    def adicionar_modal_rodoviario(self, **kwargs):
        obj = ManifestoRodoviario(**kwargs)
        self.modal_rodoviario.append(obj)
        return obj

    def adicionar_documentos(self, **kwargs):
        obj = ManifestoDocumentos(**kwargs)
        self.documentos.append(obj)
        return obj

    def adicionar_seguradora(self, **kwargs):
        obj = ManifestoSeguradora(**kwargs)
        self.seguradora.append(obj)
        return obj

    def adicionar_produto(self, **kwargs):
        obj = ManifestoProduto(**kwargs)
        self.produto.append(obj)
        return obj

    def adicionar_totais(self, **kwargs):
        obj = ManifestoTotais(**kwargs)
        self.totais.append(obj)
        return obj

    def adicionar_lacres(self, **kwargs):
        obj = ManifestoLacres(**kwargs)
        self.lacres.append(obj)
        return obj

    def adicionar_responsavel_tecnico(self, **kwargs):
        """Adiciona uma instancia de Responsavel Tecnico"""
        obj = ManifestoResponsavelTecnico(**kwargs)
        self.responsavel_tecnico.append(obj)
        return obj

    def _codigo_numerico_aleatorio(self):
        self.codigo_numerico_aleatorio = str(random.randint(0, 99999999)).zfill(8)
        return self.codigo_numerico_aleatorio

    def _dv_codigo_numerico(self, key):
        if not len(key) == 43:
            raise ValueError(
                f"Chave de acesso deve ter 43 caracteres antes de calcular o DV, chave: {key}"
            )

        weights = [2, 3, 4, 5, 6, 7, 8, 9]
        weights_size = len(weights)
        key_numbers = [int(k) for k in key]
        key_numbers.reverse()

        key_sum = 0
        for i, key_number in enumerate(key_numbers):
            # cycle though weights
            i = i % weights_size
            key_sum += key_number * weights[i]

        remainder = key_sum % 11
        if remainder == 0 or remainder == 1:
            self.dv_codigo_numerico_aleatorio = "0"
            return "0"
        self.dv_codigo_numerico_aleatorio = str(11 - remainder)
        return str(self.dv_codigo_numerico_aleatorio)

    @property
    # @memoize
    def identificador_unico(self):
        # Monta 'Id' da tag raiz <infMDFe>
        # Ex.: MDFe35080599999090910270580010000000011518005123
        key = "{uf}{ano}{mes}{cnpj}{mod}{serie}{nMDF}{tpEmis}{cMDF}".format(
            uf=CODIGOS_ESTADOS[self.uf],
            ano=self.data_emissao.strftime("%y"),
            mes=self.data_emissao.strftime("%m"),
            cnpj=so_numeros(self.emitente.cpfcnpj).zfill(14),
            mod=self.modelo,
            serie=str(self.serie).zfill(3),
            nMDF=str(self.numero_mdfe).zfill(9),
            tpEmis=str(self.forma_emissao),
            cMDF=self._codigo_numerico_aleatorio(),
        )
        return "MDFe{uf}{ano}{mes}{cnpj}{mod}{serie}{nMDF}{tpEmis}{cMDF}{cDV}".format(
            uf=CODIGOS_ESTADOS[self.uf],
            ano=self.data_emissao.strftime("%y"),
            mes=self.data_emissao.strftime("%m"),
            cnpj=so_numeros(self.emitente.cpfcnpj).zfill(14),
            mod=self.modelo,
            serie=str(self.serie).zfill(3),
            nMDF=str(self.numero_mdfe).zfill(9),
            tpEmis=str(self.forma_emissao),
            cMDF=str(self.codigo_numerico_aleatorio),
            cDV=self._dv_codigo_numerico(key),
        )


class ManifestoMunicipioCarrega(Entidade):
    # - Codigo municipio
    cMunCarrega = ""

    # - Nome do municipio
    xMunCarrega = ""


class ManifestoPercurso(Entidade):
    # - Nome da UF (2 digitos)
    UFPer = ""


class ManifestoRodoviario(Entidade):
    rntrc = ""
    ciot = None
    pedagio = None
    contratante = None
    pagamento = None
    veiculo_tracao = None
    veiculo_reboque = None


class ManifestoCIOT(Entidade):
    numero_ciot = ""
    cpfcnpj = ""


class ManifestoPedagio(Entidade):
    cnpj_fornecedor = ""
    cpfcnpj_pagador = ""
    numero_compra = ""
    valor_pedagio = Decimal()


class ManifestoContratante(Entidade):
    nome = ""
    cpfcnpj = ""
    NroContrato = ""
    vContratoGlobal = Decimal()


class ManifestoVeiculoTracao(Entidade):
    cInt = ""
    placa = ""
    RENAVAM = ""
    tara = ""
    capKG = ""
    capM3 = ""
    proprietario = None
    condutor = None
    tpRod = ""
    tpCar = ""
    UF = ""


class ManifestoVeiculoReboque(Entidade):
    cInt = ""
    placa = ""
    RENAVAM = ""
    tara = ""
    capKG = ""
    capM3 = ""
    proprietario = None
    tpCar = ""
    UF = ""


class ManifestoCondutor(Entidade):
    nome_motorista = ""
    cpf_motorista = ""


class ManifestoDocumentos(Entidade):
    # Código do municipio de descarga
    cMunDescarga = ""
    # Nome do municipio de descarga
    xMunDescarga = ""

    # Documentos vinculados
    documentos_nfe = None
    documentos_cte = None


class ManifestoDocumentosNFe(Entidade):
    chave_acesso_nfe = ""


class ManifestoDocumentosCTe(Entidade):
    chave_acesso_cte = ""


class ManifestoSeguradora(Entidade):
    # infResp - Responsavel seguro
    # 1=Emitente; 2=Tomador
    responsavel_seguro = ""
    # - CNPJ do responsavel
    cnpj_responsavel = ""

    # infSeg - Seguradora
    # - Nome da seguradora
    nome_seguradora = ""
    # - CNPJ seguradora
    cnpj_seguradora = ""

    # Apolice do Seguro
    numero_apolice = ""

    # Lista de Averbacoes
    averbacoes = None


class ManifestoAverbacao(Entidade):
    # Numero da Averbacao
    numero = ""


class ManifestoProduto(Entidade):
    # Tipo de carga
    #   01=GranelSolido
    #   02=GranelLiquido
    #   03=Frigorificada
    #   04=Conteinerizada
    #   05=CargaGeral
    #   06=Neogranel
    #   07=PerigosaGranelSolido
    #   08=PerigosaGranelLiquido
    #   09=PerigosaCargaFrigorificada
    #   10=PerigosaConteinerizada
    #   11=PerigosaCargaGeral
    tipo_carga = ""

    nome_produto = ""
    cean = ""
    ncm = ""


class ManifestoEmitente(Entidade):
    # Dados do Emitente

    # - CPF ou CNPJ (obrigatorio)
    cpfcnpj = ""

    # - Inscricao Estadual (obrigatorio)
    inscricao_estadual = ""

    # - Nome/Razao Social (obrigatorio)
    razao_social = ""

    # - Nome Fantasia
    nome_fantasia = ""

    # Endereco
    # - Logradouro (obrigatorio)
    endereco_logradouro = ""

    # - Numero (obrigatorio)
    endereco_numero = ""

    # - Complemento
    endereco_complemento = ""

    # - Bairro (obrigatorio)
    endereco_bairro = ""

    # - Codigo Municipio (opt)
    endereco_cod_municipio = ""

    # - Municipio (obrigatorio)
    endereco_municipio = ""

    # - CEP
    endereco_cep = ""

    # - UF (obrigatorio)
    endereco_uf = ""

    # - Telefone
    endereco_telefone = ""

    # - Email
    endereco_email = ""

    def __str__(self):
        return self.cpfcnpj


class ManifestoTotais(Entidade):
    # Quantidade total de CT-e relacionados no Manifesto
    qCTe = 0

    # Quantidade total de NF-e relacionadas no Manifesto
    qNFe = 0

    # Valor total da carga / mercadorias transportadas
    vCarga = Decimal()

    # - Código da unidade de medida do Peso Bruto da Carga / Mercadorias transportadas
    # Unidades: 01 – KG;  02 - TON
    cUnid = ""

    # - Peso Bruto Total da Carga / Mercadorias transportadas
    qCarga = Decimal()


class ManifestoLacres(Entidade):
    nLacre = ""


class ManifestoResponsavelTecnico(Entidade):
    # NT 2018/003
    cnpj = ""
    contato = ""
    email = ""
    fone = ""
    csrt = ""
