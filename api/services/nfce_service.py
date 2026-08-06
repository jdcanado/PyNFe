"""Serviço de emissão de NFC-e (modelo 65).

Similar ao `nfe_service`, com as particularidades da NFC-e:
- Modelo 65, consumidor final, operação interna (indicador_destino=1)
- Destinatário opcional (apenas CPF, quando informado)
- QR Code gerado com CSC/CSC ID da empresa via `SerializacaoQrcode`
  (o `infNFeSupl` é inserido no XML assinado antes do envio à SEFAZ)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from lxml import etree

from api.core.exceptions import CertificadoError, EmpresaNaoEncontrada, ValidacaoNegocioError
from api.core.logging import get_logger
from api.integrations.pynfe_adapter import (
    converter_cliente,
    converter_emitente,
    converter_pagamento_kwargs,
    converter_produto_kwargs,
)
from api.models import Empresa
from api.schemas.nfce import NFCeEmitirRequest, NFCeResponse
from api.services.certificado_service import _session_ctx, _upload_blob, obter_pem
from api.services.nfe_service import (
    STATUS_AUTORIZADA,
    STATUS_ERRO,
    STATUS_REJEITADA,
    _assinar_xml,
    _extrair_da_resposta,
    _fonte_dados_isolada,
)
from pynfe.entidades.notafiscal import NotaFiscal
from pynfe.processamento.serializacao import SerializacaoQrcode, SerializacaoXML

logger = get_logger("api.nfce_service")


def _converter_nota_nfce(schema: NFCeEmitirRequest) -> NotaFiscal:
    """Monta a NotaFiscal (modelo 65) a partir do schema, com destinatário opcional."""
    nota = NotaFiscal(
        emitente=converter_emitente(schema.emitente),
        uf=schema.uf,
        municipio=schema.municipio,
        natureza_operacao=schema.natureza_operacao,
        tipo_documento=1,  # saída
        data_emissao=schema.data_emissao or datetime.now(timezone.utc),
        modelo=65,
        serie=str(schema.serie),
        numero_nf=str(schema.numero),
        forma_emissao="1",
        finalidade_emissao="1",  # normal
        cliente_final=1,
        indicador_destino=1,  # operação interna
        indicador_presencial=schema.indicador_presencial,
        tipo_impressao_danfe=schema.tipo_impressao_danfe,
    )
    # NFC-e não exige destinatário completo (CPF opcional)
    if schema.cliente is not None:
        nota.cliente = converter_cliente(schema.cliente)

    for produto in schema.produtos:
        nota.adicionar_produto_servico(**converter_produto_kwargs(produto))
    for pagamento in schema.pagamentos:
        nota.adicionar_pagamento(**converter_pagamento_kwargs(pagamento))
    return nota


async def _obter_csc(session: Any, empresa_id: UUID) -> tuple[str, str]:
    """Retorna (csc, csc_id) da empresa para o QR Code da NFC-e."""
    async with _session_ctx(session) as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None:
            raise EmpresaNaoEncontrada(f"Empresa {empresa_id} não encontrada")
        if not empresa.csc or not empresa.csc_id:
            raise ValidacaoNegocioError("Empresa sem CSC cadastrado para emissão de NFC-e")
        return empresa.csc, empresa.csc_id


async def emitir_nfce(
    schema: NFCeEmitirRequest,
    *,
    homologacao: bool = True,
    redis: Any,
    session: Any,
    http_client: Any | None = None,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
) -> NFCeResponse:
    """Executa o pipeline completo de emissão de NFC-e e persiste o resultado."""
    empresa_id = schema.empresa_id

    # 1+2. Monta a entidade e serializa usando FonteDados isolada (por request)
    with _fonte_dados_isolada() as fonte:
        nota = _converter_nota_nfce(schema)
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

    # 5. Gera o QR Code (CSC/CSC ID da empresa) e insere o infNFeSupl no XML
    csc, csc_id = await _obter_csc(session, empresa_id)
    xml_com_qrcode, qrcode_url = SerializacaoQrcode().gerar_qrcode(
        token=csc_id,
        csc=csc,
        xml=xml_assinado,
        return_qr=True,
    )
    xml_assinado_str = etree.tostring(xml_com_qrcode, encoding="unicode", pretty_print=False)

    # 6. Envia para a SEFAZ (comunicacao do PyNFe é síncrona: requests)
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
    resultado = await asyncio.to_thread(
        comunicacao.autorizacao,
        modelo="nfce",
        nota_fiscal=xml_com_qrcode,
    )

    # 7. Processa a resposta
    status_code = resultado[0]
    if status_code != 0:
        return _resposta_erro_nfce(nota, schema, empresa_id, xml_assinado_str, resultado)

    nfe_proc = resultado[1]
    chave, protocolo, cstat = _extrair_da_resposta(nfe_proc)
    status = STATUS_AUTORIZADA if cstat in ("100", "150") else STATUS_REJEITADA
    xml_protocolado_str = etree.tostring(nfe_proc, encoding="unicode", pretty_print=False)

    # 8. Salva o XML protocolado no Blob
    try:
        await _upload_blob(
            xml_protocolado_str.encode(),
            f"nfce/{chave}.xml",
            http_client=http_client,
        )
    except Exception as exc:  # noqa: BLE001
        # Blob é camada auxiliar: falha não deve impedir a autorização
        logger.warning("Falha ao salvar XML da NFC-e no Blob: %s", exc)

    # 9. Persiste no banco
    emitida_em = schema.data_emissao or datetime.now(timezone.utc)
    autorizada_em = datetime.now(timezone.utc) if status == STATUS_AUTORIZADA else None

    id_nota = None
    async with _session_ctx(session) as db:
        from api.models import NotaFiscal as NotaFiscalModel

        registro = NotaFiscalModel(
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=int(schema.numero),
            serie=int(schema.serie),
            modelo="65",
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

    return NFCeResponse(
        id=id_nota,
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=int(schema.numero),
        serie=int(schema.serie),
        modelo="65",
        status=status,
        protocolo=protocolo or None,
        valor_total=float(nota.totais_icms_total_nota),
        qrcode_url=qrcode_url,
        emitida_em=emitida_em,
        autorizada_em=autorizada_em,
        xml_assinado=xml_assinado_str,
        xml_protocolado=xml_protocolado_str,
        mensagem=None if status == STATUS_AUTORIZADA else "Nota rejeitada pela SEFAZ",
    )


def _resposta_erro_nfce(
    nota: NotaFiscal,
    schema: NFCeEmitirRequest,
    empresa_id: UUID,
    xml_assinado_str: str,
    resultado: tuple,
) -> NFCeResponse:
    """Monta a resposta quando a SEFAZ não autoriza (status_code != 0)."""
    identificador = nota.identificador_unico or ""
    chave = identificador.removeprefix("NFe")
    return NFCeResponse(
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=int(schema.numero),
        serie=int(schema.serie),
        modelo="65",
        status=STATUS_ERRO,
        valor_total=float(nota.totais_icms_total_nota),
        xml_assinado=xml_assinado_str,
        mensagem=str(resultado[1]) if len(resultado) > 1 else "Falha na comunicação com a SEFAZ",
    )
