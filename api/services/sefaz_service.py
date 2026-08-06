"""Serviço de status dos webservices SEFAZ por UF.

Fluxo:
1. Cache KV (`sefaz:status:{uf}`) com TTL de 60s — evita chamadas repetidas.
2. Cache miss → `ComunicacaoSefaz.status_servico("nfe")` com o certificado
   da empresa (PEM em memória, via `obter_pem`).
3. Parse do XML de resposta (`retConsStatServ` → cStat, xMotivo, dhRecbto).
4. Salva o cache KV e retorna o resultado.

Para UFs sem webservice próprio, o `_get_url` do PyNFe já resolve SVRS/SVAN
através do mapeamento em `pynfe.utils.webservices`.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from lxml import etree

from api.core.exceptions import CertificadoError
from api.core.logging import get_logger
from api.services.certificado_service import obter_pem
from pynfe.utils.flags import CODIGOS_ESTADOS

logger = get_logger("api.sefaz_service")

SEFAZ_CACHE_TTL = 60  # segundos
SEFAZ_CACHE_KEY = "sefaz:status:{uf}"

# UFs atendidas (exclui AN = Ambiente Nacional e EX = Exterior)
UFS = [uf for uf in CODIGOS_ESTADOS if uf not in ("AN", "EX")]

# cStat do serviço NFeStatusServico4
CSTAT_OPERACIONAL = "107"
CSTAT_PARCIAL = "108"
CSTAT_PARADO = "109"


def _mapear_status(cstat: str) -> str:
    """Traduz o cStat do retorno para um status legível."""
    if cstat == CSTAT_OPERACIONAL:
        return "operacional"
    if cstat == CSTAT_PARCIAL:
        return "parcial"
    if cstat == CSTAT_PARADO:
        return "parado"
    return "indisponivel"


def _parse_retorno_status(xml_str: str, uf: str) -> dict:
    """Extrai cStat/xMotivo/dhRecbto do `retConsStatServ` da resposta SOAP."""
    raiz = etree.fromstring(xml_str.encode("utf-8"))
    ret = raiz.xpath(".//*[local-name()='retConsStatServ']")
    if not ret:
        return {
            "uf": uf,
            "status": "indisponivel",
            "cstat": "",
            "mensagem": "Resposta sem retConsStatServ",
        }

    node = ret[0]
    cstat = node.xpath("string(.//*[local-name()='cStat'])")
    xmotivo = node.xpath("string(.//*[local-name()='xMotivo'])")
    dh_recbto = node.xpath("string(.//*[local-name()='dhRecbto'])") or None

    return {
        "uf": uf,
        "status": _mapear_status(cstat),
        "cstat": cstat,
        "mensagem": xmotivo or None,
        "ultima_consulta": dh_recbto,
    }


async def _consultar_sefaz(uf: str, cert_pem: str, key_pem: str) -> dict:
    """Consulta o status SEFAZ da UF (síncrona, em thread) e mede o tempo."""
    from pynfe.processamento.comunicacao import ComunicacaoSefaz

    comunicacao = ComunicacaoSefaz(
        uf=uf,
        certificado=None,
        certificado_senha="",
        homologacao=True,
        cert_pem=cert_pem,
        key_pem=key_pem,
    )

    inicio = time.monotonic()
    retorno = await asyncio.to_thread(comunicacao.status_servico, "nfe")
    tempo_ms = round((time.monotonic() - inicio) * 1000, 1)

    resultado = _parse_retorno_status(retorno.text, uf)
    resultado["tempo_resposta_ms"] = tempo_ms
    if not resultado.get("ultima_consulta"):
        resultado["ultima_consulta"] = datetime.now(timezone.utc).isoformat()
    return resultado


async def verificar_status_uf(
    db: Any,
    redis: Any,
    uf: str,
    empresa_id: Any,
    *,
    ttl: int = SEFAZ_CACHE_TTL,
) -> dict:
    """Verifica o status do webservice SEFAZ de uma UF (cache KV TTL 60s).

    Cache miss → consulta a SEFAZ com o certificado da empresa e grava o
    resultado no KV (`sefaz:status:{uf}`).
    """
    uf = uf.upper()
    key = SEFAZ_CACHE_KEY.format(uf=uf)

    # 1. Cache KV
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    # 2. Certificado (usado no TLS da chamada)
    pems = await obter_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    # 3. Consulta a SEFAZ
    resultado = await _consultar_sefaz(uf, cert_pem, key_pem)

    # 4. Salva no KV (TTL injetável para testes)
    if ttl > 0:
        await redis.set(key, json.dumps(resultado), ex=ttl)

    return resultado


async def verificar_status_todos(
    db: Any,
    redis: Any,
    empresa_id: Any,
) -> list[dict]:
    """Verifica o status de todas as 27 UFs em paralelo (`asyncio.gather`).

    O certificado é obtido uma única vez (a sessão do `Depends` não é segura
    para uso concorrente); cada UF usa cache próprio de 60s.
    """
    pems = await obter_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    async def _para_uf(uf: str) -> dict:
        key = SEFAZ_CACHE_KEY.format(uf=uf)
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)
        resultado = await _consultar_sefaz(uf, cert_pem, key_pem)
        await redis.set(key, json.dumps(resultado), ex=SEFAZ_CACHE_TTL)
        return resultado

    return list(await asyncio.gather(*(_para_uf(uf) for uf in UFS)))
