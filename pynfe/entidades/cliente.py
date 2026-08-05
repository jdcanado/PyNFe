from .base import Entidade


class Cliente(Entidade):
    # Dados do Cliente
    # - Nome/Razão Social (obrigatorio)
    razao_social = ""

    # - Email
    email = ""

    # - Tipo de Documento (obrigatorio) - default CNPJ - TIPOS_DOCUMENTO
    tipo_documento = "CNPJ"

    # - Numero do Documento (obrigatorio)
    numero_documento = ""

    # - Indicador da IE do destinatário: 1 – Contribuinte ICMSpagamento à vista;
    # 2 – Contribuinte isento de inscrição; 9 – Não Contribuinte
    indicador_ie = 0

    # - Inscricao Estadual
    inscricao_estadual = ""

    # - Inscricao Municial
    inscricao_municipal = ""

    # - Inscricao SUFRAMA
    inscricao_suframa = ""

    # - Isento do ICMS (Sim/Nao)
    isento_icms = False

    # Endereco
    # - Logradouro (obrigatorio)
    endereco_logradouro = ""

    # - Numero (obrigatorio)
    endereco_numero = ""

    # - Complemento
    endereco_complemento = ""

    # - Bairro (obrigatorio)
    endereco_bairro = ""

    # - CEP
    endereco_cep = ""

    # - Pais (seleciona de lista)
    endereco_pais = ""

    # - UF (obrigatorio)
    endereco_uf = ""

    # - Municipio (obrigatorio)
    endereco_municipio = ""

    # - Código do Município (opt)
    endereco_cod_municipio = ""

    # - Telefone
    endereco_telefone = ""

    def __str__(self):
        return f"{self.tipo_documento} {self.numero_documento}"
