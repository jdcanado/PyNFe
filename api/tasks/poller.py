"""Vercel Cron: processa notas em processamento assíncrono há mais de 30s.

A cada 2 minutos (ver `vercel.json`), o poller:
1. Seleciona notas com status `PROCESSANDO` cujo `updated_at` é anterior a
   30 segundos (`SELECT ... FOR UPDATE SKIP LOCKED`, limite de 10).
2. Para cada nota, consulta o resultado do lote na SEFAZ (`consulta_recibo`).
3. Atualiza o status da nota (mantém `PROCESSANDO` se o lote ainda não foi
   processado; aplica o status final caso contrário).
4. Dispara o webhook quando o status final é atingido (autorizada, rejeitada
   ou denegada).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from lxml import etree
from sqlalchemy import select

from api.core.logging import get_logger
from api.models import NotaFiscal

logger = get_logger("api.tasks.poller")

STATUS_PROCESSANDO = "PROCESSANDO"
STATUS_AUTORIZADA = "AUTORIZADA"
STATUS_REJEITADA = "REJEITADA"
STATUS_DENEGADA = "DENEGADA"

# Status finais da autorização: ao atingir um deles, o webhook é disparado
STATUS_FINAIS = {STATUS_AUTORIZADA, STATUS_REJEITADA, STATUS_DENEGADA}

PENDENCIA_MINIMA_SEGUNDOS = 30
LOTE_MAXIMO = 10

# cStat do NFeRetAutorizacao4
CSTAT_LOTE_PROCESSADO = "104"  # lote processado com sucesso
CSTAT_LOTE_PROCESSANDO = "105"  # lote em processamento
CSTAT_AUTORIZADA = "100"
CSTAT_DENEGADA = "110"


def _mapear_status_final(cstat: str) -> str | None:
    """Traduz o cStat final da autorização para o status da nota.

    Retorna None para cStats que não representam um desfecho (ex.: 105).
    """
    if cstat == CSTAT_AUTORIZADA:
        return STATUS_AUTORIZADA
    if cstat == CSTAT_DENEGADA:
        return STATUS_DENEGADA
    return STATUS_REJEITADA


async def consultar_recibo_sefaz(db: Any, nota: NotaFiscal) -> dict:
    """Consulta o resultado do lote assíncrono na SEFAZ e devolve o status.

    Retorna `{"status": ..., "final": bool, ...}`; `final=False` indica que o
    lote ainda está em processamento (mantém o status atual da nota).
    """
    from api.models import Empresa
    from pynfe.processamento.comunicacao import ComunicacaoSefaz

    empresa = await db.get(Empresa, nota.empresa_id)
    if empresa is None or not nota.recibo:
        return {"status": nota.status, "final": False, "mensagem": "sem recibo ou empresa"}

    comunicacao = ComunicacaoSefaz(
        uf=empresa.uf or "SP",
        certificado=None,
        certificado_senha="",
        homologacao=True,
        cert_pem=empresa.cert_pem or "",
        key_pem=empresa.key_pem or "",
    )
    modelo = "nfe" if nota.modelo == "55" else "nfce"
    retorno = await asyncio.to_thread(comunicacao.consulta_recibo, modelo, nota.recibo)

    try:
        # bytes em vez de str: lxml rejeita string com declaração de encoding
        raiz = etree.fromstring(retorno.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resposta inválida no consulta_recibo: %s", exc)
        return {"status": nota.status, "final": False, "mensagem": "resposta inválida"}

    cstat_lote = raiz.xpath("string(.//*[local-name()='retConsReciNFe']/*[local-name()='cStat'])")
    if cstat_lote != CSTAT_LOTE_PROCESSADO:
        # 105 = ainda em processamento; mantém o status atual
        return {
            "status": nota.status,
            "final": False,
            "mensagem": f"lote cStat {cstat_lote or 'vazio'}",
        }

    cstat_final = raiz.xpath(
        "string(.//*[local-name()='protNFe']/*[local-name()='infProt']/*[local-name()='cStat'])"
    )
    status = _mapear_status_final(cstat_final)
    if status is None:
        return {
            "status": nota.status,
            "final": False,
            "mensagem": f"cStat final {cstat_final or 'vazio'}",
        }

    return {"status": status, "final": True, "cstat": cstat_final}


async def processar_pendentes(db: Any) -> dict:
    """Seleciona notas `PROCESSANDO` há >30s e consulta o recibo na SEFAZ.

    Usa `FOR UPDATE SKIP LOCKED` para evitar que execuções concorrentes do
    cron processem a mesma nota. Retorna `{"processed": N}`.
    """
    corte = datetime.now(timezone.utc) - timedelta(seconds=PENDENCIA_MINIMA_SEGUNDOS)
    result = await db.execute(
        select(NotaFiscal)
        .where(NotaFiscal.status == STATUS_PROCESSANDO)
        .where(NotaFiscal.updated_at < corte)
        .with_for_update(skip_locked=True)
        .limit(LOTE_MAXIMO)
    )
    pendentes = list(result.scalars().all())

    for nota in pendentes:
        resultado = await consultar_recibo_sefaz(db, nota)
        nota.status = resultado["status"]
        if resultado.get("final"):
            from api.services.webhook_service import disparar_webhook

            await disparar_webhook(nota, resultado, db)
        else:
            logger.info(
                "Nota %s ainda em processamento (cStat lote %s)",
                nota.id,
                resultado.get("mensagem"),
            )

    await db.commit()

    return {"processed": len(pendentes)}


async def handler(request: Any = None) -> dict:
    """Handler do cron da Vercel — processa notas pendentes."""
    from api.core.database import SessionFactory

    async with SessionFactory() as db:
        return await processar_pendentes(db)
