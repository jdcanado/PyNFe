"""
@author: Junior Tada, Leonardo Tada
"""

from decimal import Decimal

from .base import Entidade


class Servico(Entidade):
    valor_servico = Decimal()
    iss_retido = 0
    """ http://www1.receita.fazenda.gov.br/sistemas/nfse/tabelas-de-codigos.htm
        Lista com códigos dos serviços
    """
    item_lista = ""
    # descrição da atividade
    discriminacao = ""
    """
        1 – Exigível;
        2 – Não incidência;
        3 – Isenção;
        4 – Exportação;
        5 – Imunidade;
        6 – Exigibilidade Suspensa por Decisão Judicial;
        7 – Exigibilidade Suspensa por ProcessoAdministrativo
    """
    exigibilidade = 0
    # Lista com todos os codigos divididos por estados na pasta data/MunIBGE
    codigo_municipio = ""
    municipio_incidencia = ""
    codigo_cnae = 0
    codigo_tributacao_municipio = ""
    # Dados opcionais
    valor_deducoes = Decimal()
    valor_pis = Decimal()
    valor_confins = Decimal()
    valor_inss = Decimal()
    valor_ir = Decimal()
    valor_csll = Decimal()
    valor_iss = Decimal()
    valor_iss_retido = Decimal()
    valor_liquido = Decimal()
    outras_retencoes = Decimal()
    base_calculo = Decimal()
    aliquota = Decimal()
    desconto_incondicionado = Decimal()
    desconto_condicionado = Decimal()

    def __str__(self):
        return self.discriminacao
