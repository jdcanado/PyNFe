from pynfe.utils.flags import CODIGO_BRASIL

from .base import Entidade


class Emitente(Entidade):
    # Dados do Emitente
    # - Nome/Razao Social (obrigatorio)
    razao_social = ""

    # - Nome Fantasia
    nome_fantasia = ""

    # - CNPJ (obrigatorio)
    cnpj = ""

    # - Inscricao Estadual (obrigatorio)
    inscricao_estadual = ""

    # - CNAE Fiscal
    cnae_fiscal = ""

    # - Inscricao Municipal
    inscricao_municipal = ""

    # - Inscricao Estadual (Subst. Tributario)
    inscricao_estadual_subst_tributaria = ""

    # - Codigo de Regime Tributario (obrigatorio)
    codigo_de_regime_tributario = ""

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

    # - Pais (aceita somente Brasil)
    endereco_pais = CODIGO_BRASIL

    # - UF (obrigatorio)
    endereco_uf = ""

    # - Municipio (obrigatorio)
    endereco_municipio = ""

    # - Codigo Municipio (opt)
    endereco_cod_municipio = ""

    # - Telefone
    endereco_telefone = ""

    # Logotipo
    logotipo = None

    def __str__(self):
        return self.cnpj
