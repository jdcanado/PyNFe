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

from api.core.exceptions import CertificadoError
from api.core.logging import get_logger
from api.integrations.pynfe_adapter import converter_nota_fiscal
from api.schemas.nfe import NFeEmitirResponse
from api.schemas.nota_item import NotaFiscalSchema
from api.services.certificado_service import _session_ctx, _upload_blob, obter_pem
from pynfe.entidades import fonte_dados
from pynfe.processamento.serializacao import SerializacaoXML
from pynfe.utils import CustomXMLSigner, remover_acentos

STATUS_AUTORIZADA = "AUTORIZADA"

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


def _get_session_factory():
    """Import lazy do factory de sessão async."""
    from api.core.database import SessionFactory

    return SessionFactory


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
    redis: Any | None = None,
    session: Any | None = None,
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

    id_nota = None
    session_obj = session if session is not None else _get_session_factory()
    async with _session_ctx(session_obj) as db:
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
