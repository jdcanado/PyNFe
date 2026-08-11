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
    STATUS_PROCESSANDO_NFE,
    STATUS_REJEITADA,
    _assinar_xml,
    _extrair_da_resposta,
    _extrair_erro_sefaz,
    _extrair_prot_nfe_do_retorno,
    _extrair_recibo_do_erro,
    _fonte_dados_isolada,
    _polling_recibo,
)
from api.services.validacao_pre_envio import validar_nfce
from api.utils.crypto import encrypt_senha, hash_documento
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


async def _obter_crt(session: Any, empresa_id: UUID) -> str | None:
    """Retorna o CRT cadastrado da empresa (None se não informado)."""
    async with _session_ctx(session) as db:
        empresa = await db.get(Empresa, empresa_id)
        if empresa is None:
            return None
        return empresa.codigo_regime_tributario


async def emitir_nfce(
    schema: NFCeEmitirRequest,
    *,
    homologacao: bool = True,
    redis: Any,
    session: Any,
    http_client: Any | None = None,
    comunicacao_factory: Callable[..., Any] | None = None,
    get_pem: Callable[..., Any] | None = None,
    crt: str | None = None,
) -> NFCeResponse:
    """Executa o pipeline completo de emissão de NFC-e e persiste o resultado."""
    empresa_id = schema.empresa_id

    # 0. Validações pré-envio (espelham rejeições da SEFAZ: 704, 373, 590, 1115)
    if crt is None:
        crt = await _obter_crt(session, empresa_id)
    validar_nfce(schema, homologacao=homologacao, crt=crt)

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

    # 7. Processa a resposta (com retry de recibo quando SEFAZ devolve 103)
    status_code = resultado[0]
    recibo = None
    nfe_proc = None
    if status_code != 0:
        # Lote processado (cStat 104) já traz o protNFe com o resultado da
        # NFC-e (100/150 = autorizada; 5xx = rejeição) — usa-o diretamente.
        prot_nfe = _extrair_prot_nfe_do_retorno(resultado)
        if prot_nfe is not None:
            nfe_proc = etree.Element(
                "nfeProc",
                xmlns="http://www.portalfiscal.inf.br/nfe",
                versao="4.00",
            )
            nfe_proc.append(xml_com_qrcode)
            nfe_proc.append(prot_nfe)
            status_code = 0
        else:
            recibo = _extrair_recibo_do_erro(resultado, xml_com_qrcode)
            if recibo:
                prot = await _polling_recibo(comunicacao, "nfce", recibo)
                if prot is not None:
                    nfe_proc = etree.Element(
                        "nfeProc",
                        xmlns="http://www.portalfiscal.inf.br/nfe",
                        versao="4.00",
                    )
                    nfe_proc.append(xml_com_qrcode)
                    nfe_proc.append(prot)
                    status_code = 0

    if status_code != 0:
        if recibo:
            return await _persistir_processando_nfce(
                nota,
                schema,
                empresa_id,
                xml_assinado_str,
                recibo,
                session,
            )
        return _resposta_erro_nfce(nota, schema, empresa_id, xml_assinado_str, resultado)

    nfe_proc = resultado[1] if nfe_proc is None else nfe_proc
    chave, protocolo, cstat = _extrair_da_resposta(nfe_proc)
    status = STATUS_AUTORIZADA if cstat in ("100", "150") else STATUS_REJEITADA
    xmotivo = nfe_proc.xpath("string(.//*[local-name()='xMotivo'])") or None
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
            modelo="65",
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
        mensagem=None
        if status == STATUS_AUTORIZADA
        else (
            f"Rejeicao da SEFAZ: {cstat} - {xmotivo}" if xmotivo else "Nota rejeitada pela SEFAZ"
        ),
        cstat=cstat,
        xmotivo=xmotivo,
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
    retorno = resultado[1] if len(resultado) > 1 else None

    cstat, xmotivo = _extrair_erro_sefaz(retorno)
    if cstat and xmotivo:
        mensagem = f"Rejeicao da SEFAZ: {cstat} - {xmotivo}"
    elif hasattr(retorno, "content"):
        # Response HTTP sem XML de rejeição interpretável
        mensagem = "Falha na comunicacao com a SEFAZ (resposta sem motivo interpretavel)"
    else:
        mensagem = str(retorno) if retorno else "Falha na comunicacao com a SEFAZ"

    return NFCeResponse(
        empresa_id=empresa_id,
        chave_acesso=chave,
        numero=int(schema.numero),
        serie=int(schema.serie),
        modelo="65",
        status=STATUS_ERRO,
        valor_total=float(nota.totais_icms_total_nota),
        xml_assinado=xml_assinado_str,
        mensagem=mensagem,
        cstat=cstat,
        xmotivo=xmotivo,
    )


async def _persistir_processando_nfce(
    nota: Any,
    schema: Any,
    empresa_id: UUID,
    xml_assinado_str: str,
    recibo: str,
    session: Any,
) -> NFCeResponse:
    """Persiste a NFC-e como PROCESSANDO (lote pendente na SEFAZ)."""
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
            modelo="65",
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

        return NFCeResponse(
            id=registro.id,
            empresa_id=empresa_id,
            chave_acesso=chave,
            numero=int(schema.numero),
            serie=int(schema.serie),
            modelo="65",
            status=STATUS_PROCESSANDO_NFE,
            valor_total=float(getattr(nota, "totais_icms_total_nota", 0)),
            emitida_em=emitida_em,
            xml_assinado=xml_assinado_str,
            mensagem="Nota em processamento na SEFAZ. O resultado estara disponivel em instantes.",
            recibo=recibo,  # type: ignore[call-arg]
        )
