from .base import Entidade


class Transportadora(Entidade):
    # Dados da Transportadora
    # - Nome/Razão Social (obrigatorio)
    razao_social = ""

    # - Tipo de Documento (obrigatorio) - default CNPJ
    tipo_documento = "CNPJ"

    # - Numero do Documento (obrigatorio)
    numero_documento = ""

    # - Inscricao Estadual
    inscricao_estadual = ""

    # Endereco
    # - Logradouro (obrigatorio)
    endereco_logradouro = ""

    # - UF (obrigatorio)
    endereco_uf = ""

    # - Municipio (obrigatorio)
    endereco_municipio = ""

    def __str__(self):
        return f"{self.tipo_documento} {self.numero_documento}"
