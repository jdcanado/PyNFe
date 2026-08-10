"""Testes do serviço de emissão de NFC-e (modelo 65, QR Code com CSC)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# --- env vars ANTES dos imports da API -------------------------------------
from cryptography.fernet import Fernet
from typing_extensions import Self

os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["KV_URL"] = "redis://localhost:6379"
os.environ["KV_TOKEN"] = "test"
os.environ["BLOB_READ_WRITE_TOKEN"] = "test-blob-token"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from api.core.exceptions import ValidacaoNegocioError
from api.schemas.nfce import NFCeEmitirRequest
from api.schemas.nota_item import (
    ClienteSchema,
    CofinsSchema,
    EmitenteSchema,
    IcmsSchema,
    PagamentoSchema,
    PisSchema,
    ProdutoItemSchema,
)
from api.services.nfce_service import emitir_nfce
from api.services.nfe_service import _assinar_xml
from pynfe.processamento.serializacao import SerializacaoQrcode

SENHA_PFX = "1234"
EMPRESA_ID = uuid4()
CSC = "0123456789abcdef0123456789abcdef0123"
CSC_ID = "000001"


def gerar_pfx_bytes(senha: str = SENHA_PFX) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Teste LTDA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Teste LTDA"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return serialization.pkcs12.serialize_key_and_certificates(
        b"teste", key, cert, None, serialization.BestAvailableEncryption(senha.encode())
    )


PFX_BYTES = gerar_pfx_bytes()


def extrair_pems() -> tuple[str, str]:
    from pynfe.entidades.certificado import CertificadoA1

    key_pem, cert_pem = CertificadoA1(pfx_bytes=PFX_BYTES).separar_arquivo(SENHA_PFX)
    return key_pem.decode(), cert_pem


KEY_PEM, CERT_PEM = extrair_pems()


def schema_nfce(cliente: ClienteSchema | None = None) -> NFCeEmitirRequest:
    """Monta um NFCeEmitirRequest completo (cliente opcional)."""
    return NFCeEmitirRequest(
        empresa_id=EMPRESA_ID,
        uf="PR",
        municipio="4118402",
        natureza_operacao="VENDA",
        data_emissao=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        serie="1",
        numero="222",
        indicador_presencial=1,
        tipo_impressao_danfe=4,
        emitente=EmitenteSchema(
            razao_social="Empresa Teste LTDA",
            cnpj="99999999000199",
            inscricao_estadual="9999999999",
            codigo_de_regime_tributario="3",
            endereco_logradouro="Rua da Paz",
            endereco_numero="666",
            endereco_bairro="Sossego",
            endereco_uf="PR",
            endereco_municipio="Paranavaí",
            endereco_cod_municipio="4118402",
            endereco_cep="87704000",
        ),
        cliente=cliente,
        produtos=[
            ProdutoItemSchema(
                codigo="000328",
                descricao="Produto teste",
                ncm="99999999",
                cfop="5102",
                ean="1234567890121",
                unidade_comercial="UN",
                quantidade_comercial=12,
                valor_unitario_comercial="9.75",
                valor_total_bruto="117.00",
                icms=IcmsSchema(
                    modalidade="00",
                    origem=0,
                    valor_base_calculo="117.00",
                    aliquota="18.00",
                    valor="21.06",
                ),
                pis=PisSchema(
                    situacao_tributaria="01",
                    valor_base_calculo="117.00",
                    aliquota_percentual="0.65",
                    valor="0.76",
                ),
                cofins=CofinsSchema(
                    situacao_tributaria="01",
                    valor_base_calculo="117.00",
                    aliquota_percentual="3.00",
                    valor="3.51",
                ),
            )
        ],
        pagamentos=[PagamentoSchema(forma_pagamento="01", valor="117.00")],
    )


def nfe_proc_fake(
    chave: str = "352" + "0" * 41, cstat: str = "100", nprot: str = "352111111111111"
):
    NS = "http://www.portalfiscal.inf.br/nfe"
    raiz = etree.Element(f"{{{NS}}}nfeProc", versao="4.00")
    nfe = etree.SubElement(raiz, f"{{{NS}}}NFe")
    inf_nfe = etree.SubElement(nfe, f"{{{NS}}}infNFe", Id=f"NFe{chave}")
    etree.SubElement(inf_nfe, f"{{{NS}}}ide")
    prot = etree.SubElement(raiz, f"{{{NS}}}protNFe")
    inf_prot = etree.SubElement(prot, f"{{{NS}}}infProt")
    etree.SubElement(inf_prot, f"{{{NS}}}cStat").text = cstat
    etree.SubElement(inf_prot, f"{{{NS}}}nProt").text = nprot
    return raiz


class FakeComunicacao:
    def __init__(self, resultado: tuple) -> None:
        self.resultado = resultado
        self.modelo = None

    def autorizacao(self, modelo=None, nota_fiscal=None, **kwargs):
        self.modelo = modelo
        self.xml_enviado = nota_fiscal
        return self.resultado


class FakeSession:
    """Sessão fake: db.get retorna a empresa (com CSC); captura persistências."""

    def __init__(self, empresa: object | None = None) -> None:
        self.empresa = empresa
        self.adicionados: list = []
        self.commit_called = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, model, pk):
        return self.empresa

    def add(self, obj) -> None:
        obj.id = obj.id or uuid4()
        self.adicionados.append(obj)

    async def commit(self) -> None:
        self.commit_called = True

    async def refresh(self, obj) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class FakeHttpClient:
    def __init__(self) -> None:
        self.put_calls: list[tuple] = []

    async def put(self, url, content=None, headers=None):
        self.put_calls.append((url, content, headers))
        return _FakeResponse({"url": url, "pathname": "x"})

    async def aclose(self) -> None:
        return None


class _FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


def run(coro) -> object:
    return asyncio.run(coro)


class EmpresaFake:
    """Empresa mínima com CSC para o db.get do service."""

    def __init__(self, csc: str = CSC, csc_id: str = CSC_ID) -> None:
        self.id = EMPRESA_ID
        self.csc = csc
        self.csc_id = csc_id


async def get_pem_mock(empresa_id, *, redis=None, session=None):
    return CERT_PEM, KEY_PEM


# ---------------------------------------------------------------------------
# Emissão NFC-e
# ---------------------------------------------------------------------------


def test_emitir_nfce_autorizada_com_qrcode():
    session = FakeSession(EmpresaFake())
    redis = FakeRedis()
    http = FakeHttpClient()

    def comunicacao_factory(**kwargs):
        return FakeComunicacao((0, nfe_proc_fake()))

    resp = run(
        emitir_nfce(
            schema_nfce(),
            homologacao=True,
            redis=redis,
            session=session,
            http_client=http,
            comunicacao_factory=comunicacao_factory,
            get_pem=get_pem_mock,
        )
    )

    assert resp.status == "AUTORIZADA"
    assert resp.protocolo == "352111111111111"
    assert len(resp.chave_acesso) == 44
    assert resp.modelo == "65"

    # XML assinado com modelo 65 e campos de consumidor final
    xml = resp.xml_assinado
    assert "<mod>65</mod>" in xml
    assert "<indPres>1</indPres>" in xml
    assert "<indFinal>1</indFinal>" in xml
    # QR Code presente no XML (infNFeSupl) e na resposta
    assert "infNFeSupl" in xml
    assert resp.qrcode_url and resp.qrcode_url.startswith("http")

    # Persistência com modelo 65
    assert session.commit_called is True
    assert len(session.adicionados) == 1
    assert session.adicionados[0].modelo == "65"


def test_emitir_nfce_sem_destinatario():
    """NFC-e permite emissão sem destinatário (cliente None)."""
    session = FakeSession(EmpresaFake())
    redis = FakeRedis()

    def comunicacao_factory(**kwargs):
        return FakeComunicacao((0, nfe_proc_fake()))

    resp = run(
        emitir_nfce(
            schema_nfce(cliente=None),
            redis=redis,
            session=session,
            comunicacao_factory=comunicacao_factory,
            get_pem=get_pem_mock,
        )
    )

    assert resp.status == "AUTORIZADA"
    assert "<dest" not in resp.xml_assinado


def test_emitir_nfce_sem_csc_levanta_erro():
    """Empresa sem CSC cadastrado -> ValidacaoNegocioError."""
    session = FakeSession(EmpresaFake(csc=None, csc_id=None))
    redis = FakeRedis()

    with pytest.raises(ValidacaoNegocioError, match="CSC"):
        run(
            emitir_nfce(
                schema_nfce(),
                redis=redis,
                session=session,
                get_pem=get_pem_mock,
            )
        )


def test_qrcode_url_depende_do_csc():
    """CSCs diferentes geram hashes (parâmetro c) diferentes na URL do QR Code."""
    # Serializa e assina um XML mínimo para o SerializacaoQrcode
    xml = etree.fromstring(
        """<NFe xmlns="http://www.portalfiscal.inf.br/nfe">
          <infNFe Id="NFe35200000000000000000000000000000000000000001">
            <ide>
              <cUF>41</cUF>
              <dhEmi>2026-08-05T12:00:00-03:00</dhEmi>
              <tpAmb>2</tpAmb>
            </ide>
            <total><ICMSTot><vNF>117.00</vNF></ICMSTot></total>
          </infNFe>
        </NFe>"""
    )
    assinado = _assinar_xml(xml, KEY_PEM, CERT_PEM)

    _, url_a = SerializacaoQrcode().gerar_qrcode(
        token=CSC_ID, csc="AAAA", xml=assinado, return_qr=True
    )
    _, url_b = SerializacaoQrcode().gerar_qrcode(
        token=CSC_ID, csc="BBBB", xml=assinado, return_qr=True
    )

    assert url_a != url_b
    assert "qrcode" in url_a
