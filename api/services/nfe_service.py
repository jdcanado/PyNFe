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
from api.schemas.nfe import EventoResponse, InutilizarResponse, NFeEmitirResponse
from api.schemas.nota_item import NotaFiscalSchema
from api.services.certificado_service import _session_ctx, _upload_blob, obter_pem
from api.utils.crypto import encrypt_senha, hash_documento
from pynfe.entidades import fonte_dados
from pynfe.entidades.evento import EventoCancelarNota, EventoCartaCorrecao
from pynfe.processamento.serializacao import SerializacaoXML
from pynfe.utils import CustomXMLSigner, remover_acentos

STATUS_AUTORIZADA = "AUTORIZADA"
STATUS_CANCELADA = "CANCELADA"

logger = get_logger("api.nfe_service")
STATUS_REJEITADA = "REJEITADA"
STATUS_ERRO = "ERRO"


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

    # 6. Processa a resposta
    status_code = resultado[0]
    if status_code != 0:
        return _resposta_erro(nota, schema, empresa_id, xml_assinado_str, resultado)

    nfe_proc = resultado[1]
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
