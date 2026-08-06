"""Serviço de consulta de GTIN (código de barras / tributação aproximada).

Fluxo:
1. Cache KV (`gtin:{codigo}`) com TTL de 24h — evita chamadas repetidas à SEFAZ.
2. Cache miss → consulta à SEFAZ SP (`ComunicacaoSefaz.consulta_gtin`).
3. Parse do XML de resposta (descricao, marca, NCM, CEST, GPC).
4. Persiste o cache KV e registra a consulta em `gtin_consultas`.

GTIN não encontrado retorna `{"codigo_gtin": ..., "encontrado": false}`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from lxml import etree

from api.core.logging import get_logger

logger = get_logger("api.gtin_service")

GTIN_CACHE_TTL = 86_400  # 24 horas
GTIN_CACHE_KEY = "gtin:{codigo}"

# Serializa o acesso à sessão compartilhada entre as consultas do lote
_registro_lock = asyncio.Lock()

# cStat da SEFAZ SP que indica GTIN localizado
CSTAT_GTIN_ENCONTRADO = ("138",)


def _parse_retorno_gtin(xml_str: str, codigo_gtin: str) -> dict:
    """Extrai os dados do `retConsGTIN` do XML SOAP de resposta da SEFAZ."""
    raiz = etree.fromstring(xml_str.encode("utf-8"))
    ret = raiz.xpath(".//*[local-name()='retConsGTIN']")
    if not ret:
        return {"codigo_gtin": codigo_gtin, "encontrado": False}

    node = ret[0]
    cstat = node.xpath("string(.//*[local-name()='cStat'])")
    encontrado = cstat in CSTAT_GTIN_ENCONTRADO

    def _texto(tag: str) -> str | None:
        valor = node.xpath(f"string(.//*[local-name()='{tag}'])")
        return valor or None

    return {
        "codigo_gtin": codigo_gtin,
        "encontrado": encontrado,
        "descricao": _texto("descricao"),
        "marca": _texto("marca"),
        "ncm": _texto("ncm"),
        "cest": _texto("cest"),
        "gpc": _texto("gpc"),
    }


async def _consultar_sefaz(codigo_gtin: str) -> dict:
    """Consulta a SEFAZ SP (síncrona) em thread e devolve o resultado parseado."""
    from pynfe.processamento.comunicacao import ComunicacaoSefaz

    # Consulta GTIN não assina: cert_pem/key_pem dummy evitam criar CertificadoA1
    comunicacao = ComunicacaoSefaz(
        uf="SP",
        certificado=None,
        certificado_senha="",
        homologacao=True,
        cert_pem="",
        key_pem="",
    )
    retorno = await asyncio.to_thread(comunicacao.consulta_gtin, codigo_gtin)
    return _parse_retorno_gtin(retorno.text, codigo_gtin)


async def _registrar_consulta(db: Any, codigo_gtin: str, resultado: dict) -> None:
    """Registra a consulta (cache miss) na tabela `gtin_consultas`.

    Usa a sessão recebida diretamente (sem `async with`): a sessão do
    `Depends(get_db)` já é gerenciada pelo contexto do FastAPI — fechá-la
    aqui quebraria o request. O `_registro_lock` serializa o acesso entre
    as consultas concorrentes do lote.
    """
    from api.models import GtinConsulta

    async with _registro_lock:
        consulta = GtinConsulta(
            codigo_gtin=codigo_gtin,
            descricao=resultado.get("descricao"),
            ncm=resultado.get("ncm"),
            cest=resultado.get("cest"),
            resultado_json=json.dumps(resultado),
        )
        db.add(consulta)
        await db.commit()


async def consultar_individual(
    db: Any,
    redis: Any,
    codigo_gtin: str,
    *,
    ttl: int = GTIN_CACHE_TTL,
) -> dict:
    """Consulta um GTIN individualmente (cache KV -> SEFAZ -> registro)."""
    key = GTIN_CACHE_KEY.format(codigo=codigo_gtin)

    # 1. Cache KV
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    # 2. Cache miss: consulta a SEFAZ e faz o parse
    resultado = await _consultar_sefaz(codigo_gtin)

    # 3. Salva no KV (TTL injetável para testes)
    if ttl > 0:
        await redis.set(key, json.dumps(resultado), ex=ttl)

    # 4. Registra a consulta no banco
    await _registrar_consulta(db, codigo_gtin, resultado)

    return resultado


async def consultar_lote(db: Any, redis: Any, codigos: list[str]) -> list[dict]:
    """Consulta até 50 GTINs em paralelo (`asyncio.gather`).

    O registro no banco é serializado por `_registro_lock` porque a sessão
    recebida (do Depends) não é segura para uso concorrente.
    """
    codigos = codigos[:50]
    resultados = await asyncio.gather(
        *(consultar_individual(db, redis, codigo) for codigo in codigos)
    )
    return list(resultados)
