"""Validações pré-envio que espelham rejeições da SEFAZ.

Roda sobre o payload **antes** de serializar/assinar/enviar, retornando o
cStat provável com mensagem clara — evitando idas e vindas com a SEFAZ.

Cobertura atual (NFC-e):
- 704: dhEmi retroativo para NFC-e com DANFE Simplificado Tipo 2 (tpImp=4)
- 373: descrição do 1º item em homologação (substituição automática)
- 590: CST vs CSOSN conforme o CRT (Simples Nacional = CSOSN)
- 1115: grupo IBS/CBS obrigatório no item (Reforma Tributária)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from api.core.exceptions import ValidacaoNegocioError
from api.schemas.nfce import NFCeEmitirRequest

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

DESCRICAO_HOMOLOGACAO = "NOTA FISCAL EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"

# CSOSN (Simples Nacional): 101-900 (3 dígitos)
_CSOSN_INICIO = 101
_CSOSN_FIM = 900


def _crt_efetivo(crt: str | None, schema: NFCeEmitirRequest) -> str | None:
    """CRT prioritário: cadastro (param) > payload (emitente)."""
    if crt:
        return str(crt)
    return schema.emitente.codigo_de_regime_tributario or None


def _validar_data_emissao(schema: NFCeEmitirRequest) -> None:
    """Rejeição 704: NFC-e tpImp=4 não admite data de emissão retroativa."""
    if schema.data_emissao is None:
        return
    data_emissao = schema.data_emissao.astimezone(FUSO_BRASIL)
    hoje = datetime.now(FUSO_BRASIL).date()
    if data_emissao.date() < hoje:
        raise ValidacaoNegocioError(
            "Rejeição provável 704: NFC-e com DANFE Simplificado Tipo 2 não "
            "admite data de emissão retroativa (dhEmi anterior à data atual). "
            "Envie a data/hora atual ou omita data_emissao."
        )


def _validar_icms_regime(schema: NFCeEmitirRequest, crt: str | None) -> None:
    """Rejeição 590: CRT=1/4 (Simples) exige CSOSN; CRT=3 (Normal) exige CST."""
    crt = _crt_efetivo(crt, schema)
    if crt not in ("1", "4", "3"):
        return  # CRT ausente ou não reconhecido: não bloqueia

    eh_simples = crt in ("1", "4")
    for i, produto in enumerate(schema.produtos, start=1):
        icms = produto.icms
        if icms is None or not icms.modalidade.isdigit():
            continue
        modalidade = int(icms.modalidade)
        eh_csosn = _CSOSN_INICIO <= modalidade <= _CSOSN_FIM
        if eh_simples and not eh_csosn:
            raise ValidacaoNegocioError(
                f"Rejeição provável 590: empresa CRT={crt} (Simples Nacional) exige CSOSN "
                f"(101-900) no item {i}; recebido CST {icms.modalidade!r}."
            )
        if eh_simples and eh_csosn and not icms.csosn:
            raise ValidacaoNegocioError(
                f"Rejeição provável 590: item {i} com CSOSN {icms.modalidade!r}, "
                "mas o campo csosn não foi informado (use o mesmo valor em modalidade e csosn)."
            )
        if not eh_simples and eh_csosn:
            raise ValidacaoNegocioError(
                f"Item {i}: empresa CRT=3 (Regime Normal) exige CST (00-90); "
                f"recebido CSOSN {icms.modalidade!r}. Use CST ou ajuste o CRT."
            )


def _validar_ibscbs(schema: NFCeEmitirRequest) -> None:
    """Rejeição 1115: grupo IBS/CBS obrigatório no item (Reforma Tributária)."""
    for i, produto in enumerate(schema.produtos, start=1):
        if produto.ibscbs is None or not produto.ibscbs.cst:
            raise ValidacaoNegocioError(
                f"Rejeição provável 1115: IBS/CBS não informado no item {i}. "
                "Informe o grupo ibscbs (ex.: cst='000', c_class_trib, vbc, alíquotas e valores)."
            )


def aplicar_descricao_homologacao(schema: NFCeEmitirRequest, *, homologacao: bool) -> bool:
    """Rejeição 373: substitui a descrição do 1º item em homologação.

    Retorna True se alterou. O 1º item (nItem=1) deve ter a descrição padrão
    de ambiente de homologação quando `homologacao=True`.
    """
    if not homologacao or not schema.produtos:
        return False
    if schema.produtos[0].descricao != DESCRICAO_HOMOLOGACAO:
        schema.produtos[0].descricao = DESCRICAO_HOMOLOGACAO
        return True
    return False


def validar_nfce(
    schema: NFCeEmitirRequest,
    *,
    homologacao: bool = True,
    crt: str | None = None,
) -> bool:
    """Roda as validações pré-envio da NFC-e.

    Levanta `ValidacaoNegocioError` com o cStat provável em caso de falha.
    Retorna True se a descrição de homologação foi ajustada automaticamente.
    """
    _validar_data_emissao(schema)
    _validar_icms_regime(schema, crt)
    _validar_ibscbs(schema)
    return aplicar_descricao_homologacao(schema, homologacao=homologacao)
