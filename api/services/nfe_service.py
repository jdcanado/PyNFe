"""Serviço de emissão de NF-e — orquestra o pipeline completo.

Fluxo:
1. Monta as entidades PyNFe via adapter (schemas -> NotaFiscal).
2. Serializa a nota para XML (SerializacaoXML).
3. Carrega o certificado (cache KV, fallback Postgres).
4. Assina o XML em memória (zero I/O em disco, usando PEMs).
5. Envia para a SEFAZ usando cert_pem/key_pem diretamente.
6. Processa a resposta (protocolo/status).
7. Salva o XML protocolado no Vercel Blob.
8. Persiste a nota no banco.

O `comunicacao_factory` e os clientes (redis/sessão/HTTP) são injetáveis
para permitir testes sem SEFAZ real.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import signxml
from lxml import etree
from sqlalchemy import select

from api.core.exceptions import (
    CertificadoError,
    ConflitoEstadoError,
    EmpresaNaoEncontrada,
    NotaNaoEncontrada,
    SefazError,
    ValidacaoNegocioError,
)
from api.core.logging import get_logger
from api.integrations.pynfe_adapter import converter_nota_fiscal
from api.schemas.nfe import (
    CadastroResponse,
    ConsultarNotaResponse,
    DistribuicaoResponse,
    EventoResponse,
    InutilizarResponse,
    NFeEmitirResponse,
)
from api.schemas.nota_item import NotaFiscalSchema
from api.services.certificado_service import _session_ctx, _upload_blob, obter_pem
from api.utils.crypto import encrypt_senha, hash_documento
from pynfe.entidades import fonte_dados
from pynfe.entidades.evento import Evento, EventoCancelarNota, EventoCartaCorrecao
from pynfe.processamento.serializacao import SerializacaoXML
from pynfe.utils import CustomXMLSigner, remover_acentos
from pynfe.utils.flags import CODIGOS_ESTADOS

STATUS_AUTORIZADA = "AUTORIZADA"
STATUS_CANCELADA = "CANCELADA"

logger = get_logger("api.nfe_service")
STATUS_REJEITADA = "REJEITADA"
STATUS_ERRO = "ERRO"
STATUS_PROCESSANDO_NFE = "PROCESSANDO"

# Retry de recibo da SEFAZ (quando a autorizacao retorna 103/105)
RECIBO_MAX_TENTATIVAS = 5
RECIBO_SLEEP_SEGUNDOS = 3


@contextmanager
def _fonte_dados_isolada():
    """Troca temporariamente o singleton global por uma FonteDados por request.

    As entidades PyNFe se registram no singleton `fonte_dados._fonte_dados`
    (via `Entidade.__init__`); trocá-lo por uma instância local durante a
    montagem e serialização evita corrida entre requests concorrentes.
    """
    original = fonte_dados._fonte_dados
    instancia = fonte_dados.FonteDados()
    fonte_dados._fonte_dados = instancia
    try:
        yield instancia
    finally:
        fonte_dados._fonte_dados = original


# ---------------------------------------------------------------------------
# Assinatura em memória (PEMs, sem arquivos temporários)
# ---------------------------------------------------------------------------


def _assinar_xml(xml: etree._Element, key_pem: str, cert_pem: str) -> etree._Element:
    """Assina o XML (enveloped) usando key_pem/cert_pem em memória.

    Mesma lógica de `pynfe.processamento.assinatura.AssinaturaA1`, porém sem
    precisar do PFX/arquivos em disco.
    """
    reference = xml.find(".//*[@Id]").attrib["Id"]

    xml_str = remover_acentos(etree.tostring(xml, encoding="unicode", pretty_print=False))
    xml = etree.fromstring(xml_str)

    signer = CustomXMLSigner(
        method=signxml.methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    signer.excise_empty_xmlns_declarations = True
    signer.namespaces = {None: signer.namespaces["ds"]}

    ref_uri = f"#{reference}" if reference else None
    signed_root = signer.sign(
        xml,
        key=key_pem.encode(),
        cert=cert_pem,
        reference_uri=ref_uri,
    )

    # Reparse para garantir associação correta de namespaces (lxml 6.x)
    signed_str = etree.tostring(signed_root, encoding="unicode", pretty_print=False)
    return etree.fromstring(signed_str)


# ---------------------------------------------------------------------------
# Emissão
# ---------------------------------------------------------------------------


def _extrair_da_resposta(nfe_proc: etree._Element) -> tuple[str, str, str]:
    """Extrai (chave_acesso, protocolo, status) do nfeProc retornado pela SEFAZ."""
    inf_nfe = nfe_proc.xpath(".//*[local-name()='infNFe']")
    chave = inf_nfe[0].attrib.get("Id", "")[3:] if inf_nfe else ""

    status = nfe_proc.xpath("string(.//*[local-name()='cStat'])")
    protocolo = nfe_proc.xpath("string(.//*[local-name()='nProt'])")
    return chave, protocolo, status


def _extrair_recibo_do_erro(resultado: tuple, xml_assinado: Any) -> str | None:
    """Tenta extrair o nRec do XML de resposta quando autorizacao falha.

    Retorna o recibo (string) se o lote foi recebido (cStat 103),
    ou None se nao for possivel extrair.
    """
    if len(resultado) < 2:
        return None
    retorno = resultado[1]
    try:
        xml_ret = etree.fromstring(retorno.text or retorno.content)
    except Exception:  # noqa: BLE001
        return None
    cstat_lote = xml_ret.xpath("string(.//*[local-name()='cStat'])")
    if cstat_lote not in ("103",):
        return None
    nrec = xml_ret.xpath("string(.//*[local-name()='nRec'])")
    return nrec.strip() if nrec else None


async def _polling_recibo(
    comunicacao: Any,
    modelo: str,
    nrec: str,
    max_tentativas: int = RECIBO_MAX_TENTATIVAS,
) -> Any:
    """Faz polling do recibo com retry (sleep entre tentativas).

    Retorna o elemento protNFe (lxml) se o lote for processado (cStat 104),
    ou None se esgotar as tentativas.
    """
    for tentativa in range(1, max_tentativas + 1):
        try:
            resposta = await asyncio.to_thread(comunicacao.consulta_recibo, modelo, nrec)
            xml_resp = etree.fromstring(resposta.content)
            cstat_lote = xml_resp.xpath(
                "string(.//*[local-name()='retConsReciNFe']/*[local-name()='cStat'])"
            )
            if cstat_lote == "104":
                ns = {"ns": "http://www.portalfiscal.inf.br/nfe"}
                prot_nfe = xml_resp.xpath(".//*[local-name()='protNFe']", namespaces=ns)
                if prot_nfe and len(prot_nfe) > 0:
                    return prot_nfe[0]
            elif cstat_lote != "105":
                return None  # erro no lote; nao adianta retentar
        except Exception:  # noqa: BLE001
            logger.debug("Falha na tentativa %s de consulta_recibo", tentativa)

        if tentativa < max_tentativas:
            await asyncio.sleep(RECIBO_SLEEP_SEGUNDOS)

    return None


async def emitir_nfe(
    schema: NotaFiscalSchema,
    *,
    homologacao: bool = True,
    redis: Any,
    session: Any,
    http_client: Any | None = None,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> NFeEmitirResponse:
    """Executa o pipeline completo de emissão de NF-e e persiste o resultado."""
    empresa_id = schema.empresa_id

    # 1+2. Monta a entidade e serializa usando FonteDados isolada (por request),
    # evitando que requests concorrentes misturem entidades no singleton global.
    with _fonte_dados_isolada() as fonte:
        nota = converter_nota_fiscal(schema)
        serializador = SerializacaoXML(fonte, homologacao=homologacao)
        xml = serializador.exportar(limpar=False)

    # 3. Carrega o certificado (KV cache -> Postgres)
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=session)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    # 4. Assina o XML (zero I/O disco)
    xml_assinado = _assinar_xml(xml, key_pem, cert_pem)
    xml_assinado_str = etree.tostring(xml_assinado, encoding="unicode", pretty_print=False)

    # 5. Envia para a SEFAZ (comunicacao do PyNFe é síncrona: requests)
    if comunicacao_factory is None:
        from pynfe.processamento.comunicacao import ComunicacaoSefaz

        def comunicacao_factory(**kwargs) -> ComunicacaoSefaz:
            return ComunicacaoSefaz(**kwargs)

    comunicacao = comunicacao_factory(
        uf=schema.uf,
        certificado=None,
        certificado_senha="",
        homologacao=homologacao,
        cert_pem=cert_pem,
        key_pem=key_pem,
    )
    # autorizacao() é síncrono no PyNFe (requests); roda em thread para
    # não bloquear o event loop durante o request à SEFAZ.
    modelo_comunicacao = "nfe" if schema.modelo == 55 else "nfce"
    resultado = await asyncio.to_thread(
        comunicacao.autorizacao,
        modelo=modelo_comunicacao,
        nota_fiscal=xml_assinado,
    )

    # 6. Processa a resposta (com retry de recibo quando SEFAZ devolve 103)
    status_code = resultado[0]
    recibo = None
    nfe_proc = None
    if status_code != 0:
        recibo = _extrair_recibo_do_erro(resultado, xml_assinado)
        if recibo:
            prot = await _polling_recibo(comunicacao, modelo_comunicacao, recibo)
            if prot is not None:
                nfe_proc = etree.Element(
                    "nfeProc",
                    xmlns="http://www.portalfiscal.inf.br/nfe",
                    versao="4.00",
                )
                nfe_proc.append(xml_assinado)
                nfe_proc.append(prot)
                status_code = 0

    if status_code != 0:
        if recibo:
            return await _persistir_processando(
                nota,
                schema,
                empresa_id,
                xml_assinado_str,
                recibo,
                session,
            )
        return _resposta_erro(nota, schema, empresa_id, xml_assinado_str, resultado)

    nfe_proc = resultado[1] if nfe_proc is None else nfe_proc
    chave, protocolo, cstat = _extrair_da_resposta(nfe_proc)
    status = STATUS_AUTORIZADA if cstat in ("100", "150") else STATUS_REJEITADA
    xml_protocolado_str = etree.tostring(nfe_proc, encoding="unicode", pretty_print=False)

    # 7. Salva o XML protocolado no Blob
    nome_arquivo = f"nfe/{chave}.xml"
    try:
        await _upload_blob(
            xml_protocolado_str.encode(),
            nome_arquivo,
            http_client=http_client,
        )
    except Exception as exc:  # noqa: BLE001
        # Blob é camada auxiliar: falha não deve impedir a autorização
        logger.warning("Falha ao salvar XML da NF-e no Blob: %s", exc)

    # 8. Persiste no banco
    emitida_em = schema.data_emissao or datetime.now(timezone.utc)
    autorizada_em = datetime.now(timezone.utc) if status == STATUS_AUTORIZADA else None

    # LGPD: documento do destinatário criptografado (Fernet); só o hash SHA-256
    # é persistido em texto (irreversível)
    destinatario_doc = schema.cliente.numero_documento if schema.cliente is not None else None
    destinatario_hash = hash_documento(destinatario_doc) if destinatario_doc else None
    destinatario_enc = encrypt_senha(destinatario_doc) if destinatario_doc else None

    id_nota = None
    async with _session_ctx(session) as db:
        from api.models import NotaFiscal as NotaFiscalModel

        registro = NotaFiscalModel(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=int(schema.numero),
            serie=int(schema.serie),
            modelo=str(schema.modelo),
            status=status,
            protocolo=protocolo or None,
            xml_assinado=xml_assinado_str,
            xml_protocolado=xml_protocolado_str,
            valor_total=float(nota.totais_icms_total_nota),
            emitida_em=emitida_em,
            autorizada_em=autorizada_em,
            natureza_operacao=schema.natureza_operacao,
            destinatario=destinatario_hash,
            destinatario_cpf_encrypted=destinatario_enc,
        )
        db.add(registro)
        await db.commit()
        await db.refresh(registro)
        id_nota = registro.id

    return NFeEmitirResponse(
        id=id_nota,
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=int(schema.numero),
        serie=int(schema.serie),
        modelo=str(schema.modelo),
        status=status,
        protocolo=protocolo or None,
        valor_total=float(nota.totais_icms_total_nota),
        emitida_em=emitida_em,
        autorizada_em=autorizada_em,
        xml_assinado=xml_assinado_str,
        xml_protocolado=xml_protocolado_str,
        mensagem=None if status == STATUS_AUTORIZADA else "Nota rejeitada pela SEFAZ",
    )


def _resposta_erro(
    nota: Any,
    schema: NotaFiscalSchema,
    empresa_id: UUID,
    xml_assinado_str: str,
    resultado: tuple,
) -> NFeEmitirResponse:
    """Monta a resposta quando a SEFAZ não autoriza (status_code != 0)."""
    identificador = nota.identificador_unico or ""
    chave = identificador.removeprefix("NFe")
    return NFeEmitirResponse(
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=int(schema.numero),
        serie=int(schema.serie),
        modelo=str(schema.modelo),
        status=STATUS_ERRO,
        valor_total=float(nota.totais_icms_total_nota),
        xml_assinado=xml_assinado_str,
        mensagem=str(resultado[1]) if len(resultado) > 1 else "Falha na comunicação com a SEFAZ",
    )


async def _persistir_processando(
    nota: Any,
    schema: NotaFiscalSchema,
    empresa_id: UUID,
    xml_assinado_str: str,
    recibo: str,
    session: Any,
) -> NFeEmitirResponse:
    """Persiste a nota como PROCESSANDO (lote pendente na SEFAZ) e retorna status.

    O recibo fica armazenado para que o poller (manual ou cron) possa
    consultar o resultado posteriormente sem depender de agendamento externo.
    """
    from api.models import NotaFiscal as NotaFiscalModel

    identificador = nota.identificador_unico or ""
    chave = identificador.removeprefix("NFe")
    emitida_em = schema.data_emissao or datetime.now(timezone.utc)

    async with _session_ctx(session) as db:
        registro = NotaFiscalModel(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=int(schema.numero),
            serie=int(schema.serie),
            modelo=str(schema.modelo),
            status=STATUS_PROCESSANDO_NFE,
            recibo=recibo,
            xml_assinado=xml_assinado_str,
            valor_total=float(getattr(nota, "totais_icms_total_nota", 0)),
            emitida_em=emitida_em,
            natureza_operacao=schema.natureza_operacao,
        )
        db.add(registro)
        await db.commit()
        await db.refresh(registro)

        return NFeEmitirResponse(
            id=registro.id,
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=int(schema.numero),
            serie=int(schema.serie),
            modelo=str(schema.modelo),
            status=STATUS_PROCESSANDO_NFE,
            protocolo="",
            valor_total=float(getattr(nota, "totais_icms_total_nota", 0)),
            emitida_em=emitida_em,
            autorizada_em=None,
            xml_assinado=xml_assinado_str,
            xml_protocolado="",
            mensagem="Nota em processamento na SEFAZ. O resultado estara disponivel em instantes.",
            recibo=recibo,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Eventos: cancelamento (110111), carta de correção (110110) e inutilização
# ---------------------------------------------------------------------------

# 135 = evento registrado e vinculado à NF-e; 136 = registrado, não vinculado
_CSTAT_EVENTO_SUCESSO = {"135", "136"}
# 102 = inutilização de número homologado
_CSTAT_INUTILIZACAO_SUCESSO = {"102"}


def _modelo_comunicacao(modelo: str) -> str:
    """Mapeia o modelo da nota (55/65) para o identificador usado no PyNFe."""
    return "nfe" if modelo == "55" else "nfce"


def _criar_comunicacao(
    uf: str,
    cert_pem: str,
    key_pem: str,
    *,
    homologacao: bool,
    comunicacao_factory: Callable[..., Any] | None = None,
) -> Any:
    """Instancia o ComunicacaoSefaz com PEMs em memória (factory injetável)."""
    if comunicacao_factory is None:
        from pynfe.processamento.comunicacao import ComunicacaoSefaz

        def comunicacao_factory(**kwargs) -> ComunicacaoSefaz:
            return ComunicacaoSefaz(**kwargs)

    return comunicacao_factory(
        uf=uf,
        certificado=None,
        certificado_senha="",
        homologacao=homologacao,
        cert_pem=cert_pem,
        key_pem=key_pem,
    )


def _processar_resposta_evento(resposta: Any) -> dict:
    """Extrai cStat/xMotivo/nProt da resposta SEFAZ de envio de evento."""
    if resposta.status_code != 200:
        raise SefazError(f"Falha na comunicação com a SEFAZ (HTTP {resposta.status_code})")
    try:
        # bytes em vez de str: lxml rejeita string com declaração de encoding
        ret = etree.fromstring(resposta.content)
    except Exception as exc:
        raise SefazError("Resposta inválida da SEFAZ para o evento") from exc

    inf_evento = ret.xpath(".//*[local-name()='infEvento']")
    if not inf_evento:
        raise SefazError("Resposta da SEFAZ sem infEvento")

    cstat = inf_evento[0].xpath("string(.//*[local-name()='cStat'])")
    xmotivo = inf_evento[0].xpath("string(.//*[local-name()='xMotivo'])")
    nprot = inf_evento[0].xpath("string(.//*[local-name()='nProt'])") or None
    registrado_em = inf_evento[0].xpath("string(.//*[local-name()='dhRegEvento'])") or None

    if cstat not in _CSTAT_EVENTO_SUCESSO:
        raise SefazError(f"Evento rejeitado pela SEFAZ: {cstat} - {xmotivo}")

    return {"cstat": cstat, "xmotivo": xmotivo, "nprot": nprot, "registrado_em": registrado_em}


def _processar_resposta_inutilizacao(resposta: Any) -> dict:
    """Extrai cStat/xMotivo/nProt da resposta SEFAZ de inutilização."""
    if resposta.status_code != 200:
        raise SefazError(f"Falha na comunicação com a SEFAZ (HTTP {resposta.status_code})")
    try:
        # bytes em vez de str: lxml rejeita string com declaração de encoding
        ret = etree.fromstring(resposta.content)
    except Exception as exc:
        raise SefazError("Resposta inválida da SEFAZ para inutilização") from exc

    inf_inut = ret.xpath(".//*[local-name()='infInut']")
    if not inf_inut:
        raise SefazError("Resposta da SEFAZ sem infInut")

    cstat = inf_inut[0].xpath("string(.//*[local-name()='cStat'])")
    xmotivo = inf_inut[0].xpath("string(.//*[local-name()='xMotivo'])")
    nprot = inf_inut[0].xpath("string(.//*[local-name()='nProt'])") or None

    if cstat not in _CSTAT_INUTILIZACAO_SUCESSO:
        raise SefazError(f"Inutilização rejeitada pela SEFAZ: {cstat} - {xmotivo}")

    return {"cstat": cstat, "xmotivo": xmotivo, "nprot": nprot}


async def _buscar_nota(db: Any, empresa_id: UUID, chave_acesso: str, modelo: str) -> Any:
    """Busca a nota da empresa pela chave de acesso e modelo (55/65)."""
    from api.models import NotaFiscal as NotaFiscalModel

    result = await db.execute(
        select(NotaFiscalModel).where(
            NotaFiscalModel.empresa_id == empresa_id,
            NotaFiscalModel.chave_acesso == chave_acesso,
            NotaFiscalModel.modelo == modelo,
        )
    )
    nota = result.scalar_one_or_none()
    if nota is None:
        raise NotaNaoEncontrada("Nota não encontrada")
    return nota


async def _obter_empresa(db: Any, empresa_id: UUID) -> Any:
    """Busca a empresa emitente (CNPJ/UF para montagem do evento)."""
    from api.models import Empresa

    empresa = await db.get(Empresa, empresa_id)
    if empresa is None:
        raise EmpresaNaoEncontrada(f"Empresa {empresa_id} não encontrada")
    if not empresa.uf:
        raise ValidacaoNegocioError("Empresa sem UF cadastrada")
    return empresa


async def _enviar_evento_sefaz(
    *,
    uf: str,
    evento: Any,
    modelo: str,
    cert_pem: str,
    key_pem: str,
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
) -> tuple[dict, str]:
    """Serializa, assina e envia um evento para a SEFAZ.

    Recebe os PEMs já carregados (o certificado deve ser obtido antes de
    abrir a transação, evitando `_session_ctx` aninhados que cometam
    prematuramente).

    Retorna (informações da resposta processada, XML do evento assinado).
    """
    with _fonte_dados_isolada() as fonte:
        serializador = SerializacaoXML(fonte, homologacao=homologacao)
        xml_evento = serializador.serializar_evento(evento)

    xml_evento_assinado = _assinar_xml(xml_evento, key_pem, cert_pem)
    xml_evento_str = etree.tostring(xml_evento_assinado, encoding="unicode", pretty_print=False)

    comunicacao = _criar_comunicacao(
        uf,
        cert_pem,
        key_pem,
        homologacao=homologacao,
        comunicacao_factory=comunicacao_factory,
    )
    resposta = await asyncio.to_thread(
        comunicacao.evento,
        modelo=_modelo_comunicacao(modelo),
        evento=xml_evento_assinado,
    )
    informacoes = _processar_resposta_evento(resposta)
    return informacoes, xml_evento_str


async def cancelar_nota(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    chave_acesso: str,
    justificativa: str,
    *,
    protocolo: str | None = None,
    modelo: str = "55",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> EventoResponse:
    """Cancela uma NF-e/NFC-e (evento 110111) e atualiza o status da nota."""
    # Certificado antes da transação (evita `_session_ctx` aninhado que comita
    # prematuramente a transação de persistência)
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    async with _session_ctx(db) as session:
        nota = await _buscar_nota(session, empresa_id, chave_acesso, modelo)
        if nota.status == STATUS_CANCELADA:
            raise ConflitoEstadoError("Nota já cancelada")

        empresa = await _obter_empresa(session, empresa_id)
        protocolo = protocolo or nota.protocolo
        if not protocolo:
            raise ValidacaoNegocioError("Nota sem protocolo de autorização para cancelamento")

        evento = EventoCancelarNota(
            cnpj=empresa.cnpj,
            chave=chave_acesso,
            uf=empresa.uf,
            data_emissao=datetime.now(timezone.utc),
            protocolo=protocolo,
            justificativa=justificativa,
        )
        informacoes, xml_evento_str = await _enviar_evento_sefaz(
            uf=empresa.uf,
            evento=evento,
            modelo=modelo,
            cert_pem=cert_pem,
            key_pem=key_pem,
            homologacao=homologacao,
            comunicacao_factory=comunicacao_factory,
        )

        nota.status = STATUS_CANCELADA
        nota.eventos = (nota.eventos or []) + [
            {
                "tipo": "cancelamento",
                "tp_evento": "110111",
                "chave_acesso": chave_acesso,
                "data_evento": datetime.now(timezone.utc).isoformat(),
                "cstat": informacoes["cstat"],
                "xmotivo": informacoes["xmotivo"],
                "nprot": informacoes["nprot"],
                "protocolo_autorizacao": protocolo,
                "justificativa": justificativa,
                "xml_evento": xml_evento_str,
            }
        ]
        await session.commit()

    return EventoResponse(
        chave_acesso=chave_acesso,
        modelo=modelo,
        tp_evento="110111",
        status=STATUS_CANCELADA,
        cstat=informacoes["cstat"],
        xmotivo=informacoes["xmotivo"],
        nprot=informacoes["nprot"],
        registrado_em=informacoes["registrado_em"],
        xml_evento=xml_evento_str,
    )


async def carta_correcao_nota(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    chave_acesso: str,
    correcao: str,
    *,
    modelo: str = "55",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> EventoResponse:
    """Envia carta de correção (evento 110110) e registra na nota."""
    # Certificado antes da transação (evita `_session_ctx` aninhado que comita
    # prematuramente a transação de persistência)
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    async with _session_ctx(db) as session:
        nota = await _buscar_nota(session, empresa_id, chave_acesso, modelo)
        if nota.status != STATUS_AUTORIZADA:
            raise ConflitoEstadoError("Carta de correção exige nota autorizada")

        empresa = await _obter_empresa(session, empresa_id)

        # Carta de correção é sequencial por nota (nSeqEvento)
        n_seq = 1 + sum(1 for ev in (nota.eventos or []) if ev.get("tp_evento") == "110110")
        evento = EventoCartaCorrecao(
            cnpj=empresa.cnpj,
            chave=chave_acesso,
            uf=empresa.uf,
            data_emissao=datetime.now(timezone.utc),
            correcao=correcao,
            n_seq_evento=n_seq,
        )
        informacoes, xml_evento_str = await _enviar_evento_sefaz(
            uf=empresa.uf,
            evento=evento,
            modelo=modelo,
            cert_pem=cert_pem,
            key_pem=key_pem,
            homologacao=homologacao,
            comunicacao_factory=comunicacao_factory,
        )

        nota.eventos = (nota.eventos or []) + [
            {
                "tipo": "carta_correcao",
                "tp_evento": "110110",
                "chave_acesso": chave_acesso,
                "data_evento": datetime.now(timezone.utc).isoformat(),
                "n_seq_evento": n_seq,
                "cstat": informacoes["cstat"],
                "xmotivo": informacoes["xmotivo"],
                "nprot": informacoes["nprot"],
                "correcao": correcao,
                "xml_evento": xml_evento_str,
            }
        ]
        await session.commit()

    return EventoResponse(
        chave_acesso=chave_acesso,
        modelo=modelo,
        tp_evento="110110",
        status="REGISTRADO",
        cstat=informacoes["cstat"],
        xmotivo=informacoes["xmotivo"],
        nprot=informacoes["nprot"],
        registrado_em=informacoes["registrado_em"],
        xml_evento=xml_evento_str,
    )


async def inutilizar_nota(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    cnpj: str,
    serie: int,
    numero_inicial: int,
    numero_final: int,
    justificativa: str,
    *,
    ano: int | None = None,
    modelo: str = "55",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> InutilizarResponse:
    """Inutiliza uma faixa de numeração junto à SEFAZ (não há nota envolvida)."""
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    async with _session_ctx(db) as session:
        empresa = await _obter_empresa(session, empresa_id)

    comunicacao = _criar_comunicacao(
        empresa.uf,
        cert_pem,
        key_pem,
        homologacao=homologacao,
        comunicacao_factory=comunicacao_factory,
    )
    resposta = await asyncio.to_thread(
        comunicacao.inutilizacao,
        modelo=_modelo_comunicacao(modelo),
        cnpj=cnpj,
        numero_inicial=numero_inicial,
        numero_final=numero_final,
        justificativa=justificativa,
        ano=ano,
        serie=str(serie),
    )
    informacoes = _processar_resposta_inutilizacao(resposta)

    return InutilizarResponse(
        empresa_id=empresa_id,
        cnpj=cnpj,
        modelo=modelo,
        serie=serie,
        numero_inicial=numero_inicial,
        numero_final=numero_final,
        status="INUTILIZADA",
        cstat=informacoes["cstat"],
        xmotivo=informacoes["xmotivo"],
        nprot=informacoes["nprot"],
    )


# ---------------------------------------------------------------------------
# Consultas: situação da nota (consulta_nota), distribuição de DF-e e cadastro
# ---------------------------------------------------------------------------

# cStat do NFeConsultaProtocolo4
_CSTAT_CONSULTA_STATUS = {
    "100": "autorizada",
    "101": "cancelada",
    "135": "autorizada_fora_prazo",
    "151": "cancelada_fora_prazo",
    "155": "cancelada_fora_prazo",
    "217": "nao_encontrada",
}


def _codigo_uf_para_sigla(codigo: str) -> str:
    """Converte código IBGE da UF (2 dígitos) em sigla, ex.: '35' -> 'SP'."""
    inverso = {v: k for k, v in CODIGOS_ESTADOS.items()}
    return inverso.get(codigo.zfill(2), "")


def _parse_retorno_consulta(xml_bytes: bytes) -> dict:
    """Extrai cStat/xMotivo/protocolo do `retConsSitNFe` da resposta SOAP."""
    raiz = etree.fromstring(xml_bytes)
    ret = raiz.xpath(".//*[local-name()='retConsSitNFe']")
    if not ret:
        return {"cstat": "", "xmotivo": "Resposta sem retConsSitNFe"}

    node = ret[0]
    cstat = node.xpath("string(.//*[local-name()='cStat'])")
    xmotivo = node.xpath("string(.//*[local-name()='xMotivo'])")
    tpamb = node.xpath("string(.//*[local-name()='tpAmb'])") or None
    dh_recbto = node.xpath("string(.//*[local-name()='dhRecbto'])") or None
    nprot = (
        node.xpath(
            "string(.//*[local-name()='protNFe']/*[local-name()='infProt']/*[local-name()='nProt'])"
        )
        or None
    )

    # Cancelamento registrado como evento (procEventoNFe com tpEvento 110111)
    tp_eventos = node.xpath(".//*[local-name()='procEventoNFe']//*[local-name()='tpEvento']/text()")
    if nprot is None:
        nprot = node.xpath("string(.//*[local-name()='nProt'])") or None

    status = _CSTAT_CONSULTA_STATUS.get(cstat, "consulta")
    if "110111" in tp_eventos:
        status = "cancelada"
    if cstat == "101":
        status = "cancelada"

    return {
        "status": status,
        "cstat": cstat,
        "xmotivo": xmotivo,
        "ambiente": tpamb,
        "protocolo": nprot,
        "dh_recbto": dh_recbto,
    }


def _parse_retorno_distribuicao(xml_bytes: bytes) -> dict:
    """Extrai cStat/ultNSU/maxNSU/docZip do `retDistDFeInt` da resposta SOAP."""
    raiz = etree.fromstring(xml_bytes)
    ret = raiz.xpath(".//*[local-name()='retDistDFeInt']")
    if not ret:
        return {"cstat": "", "xmotivo": "Resposta sem retDistDFeInt"}

    node = ret[0]
    cstat = node.xpath("string(.//*[local-name()='cStat'])")
    xmotivo = node.xpath("string(.//*[local-name()='xMotivo'])")
    ult_nsu = node.xpath("string(.//*[local-name()='ultNSU'])") or None
    max_nsu = node.xpath("string(.//*[local-name()='maxNSU'])") or None

    documentos = []
    for doc in node.xpath(".//*[local-name()='docZip']"):
        documentos.append(
            {
                "nsu": doc.get("NSU"),
                "schema": doc.get("schema"),
                "conteudo_base64": doc.text or "",
            }
        )

    return {
        "cstat": cstat,
        "xmotivo": xmotivo,
        "ult_nsu": ult_nsu,
        "max_nsu": max_nsu,
        "documentos": documentos or None,
    }


def _parse_retorno_cadastro(xml_bytes: bytes) -> dict:
    """Extrai cStat/xMotivo e lista de contribuintes do `retConsCad`."""
    raiz = etree.fromstring(xml_bytes)
    ret = raiz.xpath(".//*[local-name()='retConsCad']")
    if not ret:
        return {"cstat": "", "xmotivo": "Resposta sem retConsCad"}

    node = ret[0]
    inf = node.xpath(".//*[local-name()='infCons']")
    if inf:
        inf = inf[0]
        cstat = inf.xpath("string(.//*[local-name()='cStat'])")
        xmotivo = inf.xpath("string(.//*[local-name()='xMotivo'])")
    else:
        cstat = ""
        xmotivo = ""

    contribuintes = []
    for cad in node.xpath(".//*[local-name()='infCad']"):
        endereco = (
            cad.xpath(".//*[local-name()='ender']")[0]
            if cad.xpath(".//*[local-name()='ender']")
            else None
        )
        contribuintes.append(
            {
                "razao_social": cad.xpath("string(.//*[local-name()='xNome'])") or None,
                "cnpj": cad.xpath("string(.//*[local-name()='CNPJ'])") or None,
                "cpf": cad.xpath("string(.//*[local-name()='CPF'])") or None,
                "ie": cad.xpath("string(.//*[local-name()='IE'])") or None,
                "situacao": cad.xpath("string(.//*[local-name()='cSit'])") or None,
                "indicador_nfe": cad.xpath("string(.//*[local-name()='indCredNFe'])") or None,
                "indicador_cte": cad.xpath("string(.//*[local-name()='indCredCTe'])") or None,
                "logradouro": endereco.xpath("string(.//*[local-name()='xLgr'])")
                if endereco is not None
                else None,
                "numero": endereco.xpath("string(.//*[local-name()='nro'])")
                if endereco is not None
                else None,
                "bairro": endereco.xpath("string(.//*[local-name()='xBairro'])")
                if endereco is not None
                else None,
                "municipio": endereco.xpath("string(.//*[local-name()='xMun'])")
                if endereco is not None
                else None,
                "uf": cad.xpath("string(*[local-name()='UF'])") or None,
                "cep": endereco.xpath("string(.//*[local-name()='CEP'])")
                if endereco is not None
                else None,
            }
        )

    return {
        "cstat": cstat,
        "xmotivo": xmotivo,
        "contribuintes": contribuintes or None,
    }


async def consultar_nota_sefaz(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    chave_acesso: str,
    *,
    modelo: str = "55",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> ConsultarNotaResponse:
    """Consulta a situação de uma NF-e/NFC-e na SEFAZ pela chave de acesso.

    A UF é extraída dos 2 primeiros dígitos da chave (código IBGE).
    """
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    uf = _codigo_uf_para_sigla(chave_acesso[:2])
    if not uf:
        raise ValidacaoNegocioError(f"Chave com UF desconhecida: {chave_acesso[:2]}")

    comunicacao = _criar_comunicacao(
        uf,
        cert_pem,
        key_pem,
        homologacao=homologacao,
        comunicacao_factory=comunicacao_factory,
    )
    resposta = await asyncio.to_thread(
        comunicacao.consulta_nota,
        _modelo_comunicacao(modelo),
        chave_acesso,
    )
    if resposta.status_code != 200:
        raise SefazError(f"Falha na comunicação com a SEFAZ (HTTP {resposta.status_code})")
    try:
        dados = _parse_retorno_consulta(resposta.content)
    except Exception as exc:
        raise SefazError("Resposta inválida da SEFAZ para consulta de situação") from exc

    return ConsultarNotaResponse(
        chave_acesso=chave_acesso,
        modelo=modelo,
        status=dados["status"],
        cstat=dados["cstat"],
        xmotivo=dados["xmotivo"],
        ambiente=dados["ambiente"],
        protocolo=dados["protocolo"],
        dh_recbto=datetime.fromisoformat(dados["dh_recbto"]) if dados.get("dh_recbto") else None,
        xml_raw=resposta.text,
    )


async def consultar_distribuicao(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    *,
    cnpj: str | None = None,
    cpf: str | None = None,
    chave: str | None = None,
    nsu: int = 0,
    consulta_nsu_especifico: bool = False,
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> DistribuicaoResponse:
    """Consulta a distribuição de DF-e no ambiente nacional (NFeDistribuicaoDFe).

    Tipos de consulta: `consChNFe` (chave), `consNSU` (NSU específico) ou
    `distNSU` (a partir do último NSU).
    """
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    # UF do interessado para o cUFAutor (ambiente nacional)
    empresa = await _obter_empresa(db, empresa_id)
    comunicacao = _criar_comunicacao(
        empresa.uf,
        cert_pem,
        key_pem,
        homologacao=homologacao,
        comunicacao_factory=comunicacao_factory,
    )
    resposta = await asyncio.to_thread(
        comunicacao.consulta_distribuicao,
        cnpj=cnpj,
        cpf=cpf,
        chave=chave,
        nsu=nsu,
        consulta_nsu_especifico=consulta_nsu_especifico,
    )
    if resposta.status_code != 200:
        raise SefazError(f"Falha na comunicação com a SEFAZ (HTTP {resposta.status_code})")
    try:
        dados = _parse_retorno_distribuicao(resposta.content)
    except Exception as exc:
        raise SefazError("Resposta inválida da SEFAZ para distribuição de DF-e") from exc

    if chave:
        tipo = "consChNFe"
    elif consulta_nsu_especifico:
        tipo = "consNSU"
    else:
        tipo = "distNSU"

    return DistribuicaoResponse(
        tipo=tipo,
        cstat=dados["cstat"],
        xmotivo=dados["xmotivo"],
        ult_nsu=dados["ult_nsu"],
        max_nsu=dados["max_nsu"],
        documentos=dados["documentos"],
        xml_raw=resposta.text,
    )


async def consultar_cadastro(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    *,
    uf: str,
    documento: str,
    tipo: str = "CNPJ",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> CadastroResponse:
    """Consulta o cadastro de contribuintes na SEFAZ (CadConsultaCadastro4).

    `tipo` pode ser CNPJ (padrão), CPF ou IE.
    """
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    comunicacao = _criar_comunicacao(
        uf,
        cert_pem,
        key_pem,
        homologacao=homologacao,
        comunicacao_factory=comunicacao_factory,
    )
    resposta = await asyncio.to_thread(
        comunicacao.consulta_cadastro,
        "nfe",
        documento,
        tipo.upper(),
        uf,
    )
    if resposta.status_code != 200:
        raise SefazError(f"Falha na comunicação com a SEFAZ (HTTP {resposta.status_code})")
    try:
        dados = _parse_retorno_cadastro(resposta.content)
    except Exception as exc:
        raise SefazError("Resposta inválida da SEFAZ para consulta de cadastro") from exc

    return CadastroResponse(
        uf=uf.upper(),
        documento=documento,
        tipo_documento=tipo.upper(),
        cstat=dados["cstat"],
        xmotivo=dados["xmotivo"],
        contribuintes=dados["contribuintes"],
        xml_raw=resposta.text,
    )


async def operacao_nao_realizada(
    db: Any,
    redis: Any,
    empresa_id: UUID,
    chave_acesso: str,
    justificativa: str,
    *,
    modelo: str = "55",
    homologacao: bool = True,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> EventoResponse:
    """Registra o evento de operação não realizada (110112) para uma nota autorizada.

    Não altera o status da nota (diferente do cancelamento); apenas registra o
    evento no JSONB `eventos`.
    """
    get_pem = get_pem or obter_pem
    pems = await get_pem(empresa_id, redis=redis, session=db)
    if pems is None:
        raise CertificadoError("Empresa sem certificado digital cadastrado")
    cert_pem, key_pem = pems

    async with _session_ctx(db) as session:
        nota = await _buscar_nota(session, empresa_id, chave_acesso, modelo)
        if nota.status != STATUS_AUTORIZADA:
            raise ConflitoEstadoError("Operação não realizada exige nota autorizada")

        empresa = await _obter_empresa(session, empresa_id)

        evento = Evento(
            cnpj=empresa.cnpj,
            chave=chave_acesso,
            uf=empresa.uf,
            data_emissao=datetime.now(timezone.utc),
            n_seq_evento=1,
            tp_evento="110112",
            descricao="Operacao nao Realizada",
            justificativa=justificativa,
        )
        informacoes, xml_evento_str = await _enviar_evento_sefaz(
            uf=empresa.uf,
            evento=evento,
            modelo=modelo,
            cert_pem=cert_pem,
            key_pem=key_pem,
            homologacao=homologacao,
            comunicacao_factory=comunicacao_factory,
        )

        nota.eventos = (nota.eventos or []) + [
            {
                "tipo": "operacao_nao_realizada",
                "tp_evento": "110112",
                "chave_acesso": chave_acesso,
                "data_evento": datetime.now(timezone.utc).isoformat(),
                "cstat": informacoes["cstat"],
                "xmotivo": informacoes["xmotivo"],
                "nprot": informacoes["nprot"],
                "justificativa": justificativa,
                "xml_evento": xml_evento_str,
            }
        ]
        await session.commit()

    return EventoResponse(
        chave_acesso=chave_acesso,
        modelo=modelo,
        tp_evento="110112",
        status="REGISTRADO",
        cstat=informacoes["cstat"],
        xmotivo=informacoes["xmotivo"],
        nprot=informacoes["nprot"],
        registrado_em=informacoes["registrado_em"],
        xml_evento=xml_evento_str,
    )
