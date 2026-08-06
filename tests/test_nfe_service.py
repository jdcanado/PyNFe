"""Testes do serviço de emissão de NF-e (pipeline completo com mocks).

O pipeline de emissão é testado sem SEFAZ real: a comunicação é injetada via
`comunicacao_factory` (mock), o certificado via `get_pem` e as camadas de
persistência/blob via sessão/HTTP fakes.
"""

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

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from api.core.exceptions import CertificadoError
from api.schemas.nota_item import (
    ClienteSchema,
    CofinsSchema,
    EmitenteSchema,
    IcmsSchema,
    NotaFiscalSchema,
    PagamentoSchema,
    PisSchema,
    ProdutoItemSchema,
)
from api.services.nfe_service import (
    STATUS_AUTORIZADA,
    STATUS_ERRO,
    _assinar_xml,
    _extrair_da_resposta,
    emitir_nfe,
)
from pynfe.entidades.fonte_dados import _fonte_dados

SENHA_PFX = "1234"
EMPRESA_ID = uuid4()


def gerar_pfx_bytes(senha: str = SENHA_PFX) -> bytes:
    """Gera um certificado A1 self-signed em formato PFX (memória)."""
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
        b"teste",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(senha.encode()),
    )


PFX_BYTES = gerar_pfx_bytes()


def extrair_pems() -> tuple[str, str]:
    """Extrai (key_pem, cert_pem) do PFX de teste."""
    from pynfe.entidades.certificado import CertificadoA1

    key_pem, cert_pem = CertificadoA1(pfx_bytes=PFX_BYTES).separar_arquivo(SENHA_PFX)
    return key_pem.decode(), cert_pem


KEY_PEM, CERT_PEM = extrair_pems()


def schema_nfe() -> NotaFiscalSchema:
    """Monta um NotaFiscalSchema completo para emissão."""
    return NotaFiscalSchema(
        empresa_id=EMPRESA_ID,
        uf="PR",
        municipio="4118402",
        natureza_operacao="VENDA",
        tipo_documento=1,
        data_emissao=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        modelo=55,
        serie="1",
        numero="111",
        finalidade_emissao="1",
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
        cliente=ClienteSchema(
            razao_social="JOSE DA SILVA",
            tipo_documento="CPF",
            numero_documento="12345678900",
            indicador_ie=9,
            endereco_logradouro="Rua dos Bobos",
            endereco_numero="Zero",
            endereco_bairro="Aquele Mesmo",
            endereco_uf="DF",
            endereco_municipio="Brasilia",
            endereco_cep="12345123",
        ),
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
    chave: str = "351" + "0" * 41, cstat: str = "100", nprot: str = "351111111111111"
):
    """Monta um nfeProc fake (resposta de sucesso da SEFAZ)."""
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
    """Mock da comunicação SEFAZ."""

    def __init__(self, resultado: tuple) -> None:
        self.resultado = resultado
        self.kwargs_recebidos = None
        self.xml_enviado = None

    def autorizacao(self, modelo=None, nota_fiscal=None, **kwargs):
        self.modelo = modelo
        self.xml_enviado = nota_fiscal
        return self.resultado


class FakeSession:
    """Sessão async fake: captura o registro persistido."""

    def __init__(self) -> None:
        self.adicionados: list = []
        self.commit_called = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args) -> None:
        return None

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


# ---------------------------------------------------------------------------
# Assinatura / extração de resposta
# ---------------------------------------------------------------------------


def test_assinar_xml_gera_assinatura():
    xml = etree.fromstring(
        """<NFe xmlns="http://www.portalfiscal.inf.br/nfe">
          <infNFe Id="NFe35100000000000000000000000000000000000000001">
            <ide><cUF>41</cUF></ide>
          </infNFe>
        </NFe>"""
    )
    assinado = _assinar_xml(xml, KEY_PEM, CERT_PEM)
    assert assinado.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature") is not None


def test_extrair_da_resposta():
    chave = "351" + "0" * 41
    proc = nfe_proc_fake(chave=chave, cstat="100", nprot="351111111111111")
    chave_extraida, protocolo, cstat = _extrair_da_resposta(proc)
    assert chave_extraida == chave
    assert protocolo == "351111111111111"
    assert cstat == "100"


# ---------------------------------------------------------------------------
# Emissão (pipeline completo com mocks)
# ---------------------------------------------------------------------------


def test_emitir_nfe_autorizada_persiste_e_envia_blob():
    _fonte_dados.limpar_dados()
    session = FakeSession()
    redis = FakeRedis()
    http = FakeHttpClient()

    async def get_pem(empresa_id, *, redis=None, session=None):
        return CERT_PEM, KEY_PEM

    def comunicacao_factory(**kwargs):
        return FakeComunicacao((0, nfe_proc_fake()))

    resp = run(
        emitir_nfe(
            schema_nfe(),
            homologacao=True,
            redis=redis,
            session=session,
            http_client=http,
            comunicacao_factory=comunicacao_factory,
            get_pem=get_pem,
        )
    )

    assert resp.status == STATUS_AUTORIZADA
    assert resp.protocolo == "351111111111111"
    assert len(resp.chave_acesso) == 44
    assert resp.numero == 111
    assert resp.serie == 1
    assert resp.modelo == "55"
    assert resp.valor_total == 117.00
    assert resp.id is not None

    # Persistência
    assert session.commit_called is True
    assert len(session.adicionados) == 1
    registro = session.adicionados[0]
    assert registro.chave_acesso == resp.chave_acesso
    assert registro.status == STATUS_AUTORIZADA
    assert registro.protocolo == "351111111111111"
    assert "Signature" in registro.xml_assinado
    assert "nfeProc" in registro.xml_protocolado

    # Blob
    assert len(http.put_calls) == 1
    url, content, _ = http.put_calls[0]
    assert f"nfe/{resp.chave_acesso}.xml" in url
    assert b"nfeProc" in content


def test_emitir_nfe_sem_certificado_levanta_erro():
    _fonte_dados.limpar_dados()

    async def get_pem(empresa_id, *, redis=None, session=None):
        return None

    try:
        run(emitir_nfe(schema_nfe(), redis=FakeRedis(), session=FakeSession(), get_pem=get_pem))
    except CertificadoError as exc:
        assert "certificado" in str(exc)
    else:
        raise AssertionError("deveria levantar ValueError sem certificado")


def test_emitir_nfe_falha_sefaz_retorna_status_erro():
    _fonte_dados.limpar_dados()
    session = FakeSession()

    async def get_pem(empresa_id, *, redis=None, session=None):
        return CERT_PEM, KEY_PEM

    def comunicacao_factory(**kwargs):
        return FakeComunicacao((1, "erro de comunicação", None))

    resp = run(
        emitir_nfe(
            schema_nfe(),
            redis=FakeRedis(),
            session=session,
            comunicacao_factory=comunicacao_factory,
            get_pem=get_pem,
        )
    )

    assert resp.status == STATUS_ERRO
    assert "erro de comunicação" in resp.mensagem
    assert session.commit_called is False  # não persiste em erro
