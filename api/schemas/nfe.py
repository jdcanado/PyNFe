"""Schemas de NF-e (modelo 55): emissão, resposta, cancelamento e inutilização."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from api.schemas.common import validar_chave_acesso, validar_cnpj


class CancelarRequest(BaseModel):
    """Requisição de cancelamento de NF-e.

    `protocolo` é opcional: quando ausente, a API usa o protocolo de
    autorização persistido na nota.
    """

    chave_acesso: str
    protocolo: str | None = Field(default=None, min_length=15, max_length=15)
    justificativa: str = Field(min_length=15, max_length=255)

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)


class CartaCorrecaoRequest(BaseModel):
    """Requisição de carta de correção (evento 110110)."""

    chave_acesso: str
    correcao: str = Field(min_length=15, max_length=1000)

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)


class InutilizarRequest(BaseModel):
    """Requisição de inutilização de numeração de NF-e."""

    cnpj: str
    ano: int | None = Field(default=None, ge=2000, le=2100)
    serie: int = Field(ge=0, le=999)
    numero_inicial: int = Field(ge=1)
    numero_final: int = Field(ge=1)
    justificativa: str = Field(min_length=15, max_length=255)

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str) -> str:
        return validar_cnpj(v)

    @field_validator("numero_final")
    @classmethod
    def _validar_intervalo(cls, v: int, info) -> int:
        if "numero_inicial" in info.data and v < info.data["numero_inicial"]:
            raise ValueError("numero_final deve ser >= numero_inicial")
        return v


class EventoResponse(BaseModel):
    """Resposta do envio de um evento de NF-e/NFC-e (cancelamento, carta de correção)."""

    chave_acesso: str = Field(min_length=44, max_length=44)
    modelo: str = "55"
    tp_evento: str
    status: str
    cstat: str
    xmotivo: str
    nprot: str | None = None
    registrado_em: datetime | None = None
    xml_evento: str | None = None


class InutilizarResponse(BaseModel):
    """Resposta da inutilização de numeração."""

    empresa_id: UUID
    cnpj: str = Field(min_length=14, max_length=14)
    modelo: str = "55"
    serie: int
    numero_inicial: int
    numero_final: int
    status: str
    cstat: str
    xmotivo: str
    nprot: str | None = None


class NotaFiscalResumo(BaseModel):
    """Resumo de uma nota para listagem (sem XML)."""

    id: UUID
    chave_acesso: str = Field(min_length=44, max_length=44)
    modelo: str = "55"
    status: str
    valor_total: float | None = None
    data_emissao: datetime | None = None
    natureza_operacao: str | None = None
    destinatario: str | None = None


class NFeEmitirResponse(BaseModel):
    """Resposta da emissão de NF-e."""

    id: UUID | None = None
    empresa_id: UUID
    chave_acesso: str = Field(min_length=44, max_length=44)
    numero: int
    serie: int
    modelo: str = "55"
    status: str
    protocolo: str | None = None
    valor_total: float | None = None
    emitida_em: datetime | None = None
    autorizada_em: datetime | None = None
    xml_assinado: str | None = None
    xml_protocolado: str | None = None
    mensagem: str | None = None
    recibo: str | None = None


class ConsultarNotaRequest(BaseModel):
    """Requisição de consulta da situação de NF-e/NFC-e na SEFAZ (NFeConsultaProtocolo4)."""

    chave_acesso: str

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)


class ConsultarNotaResponse(BaseModel):
    """Resposta da consulta de situação da nota na SEFAZ."""

    chave_acesso: str = Field(min_length=44, max_length=44)
    modelo: str = "55"
    status: str
    cstat: str
    xmotivo: str
    ambiente: str | None = None
    protocolo: str | None = None
    dh_recbto: datetime | None = None
    xml_raw: str | None = None


class DistribuicaoRequest(BaseModel):
    """Requisição de distribuição de DF-e (NFeDistribuicaoDFe).

    O tipo de consulta é definido pela combinação de campos:
    - `chave` presente -> consChNFe
    - `consulta_nsu_especifico=True` -> consNSU
    - ambos ausentes -> distNSU
    """

    cnpj: str | None = None
    cpf: str | None = None
    chave: str | None = None
    nsu: int = Field(default=0, ge=0, le=999999999999999)
    consulta_nsu_especifico: bool = False

    @field_validator("cnpj")
    @classmethod
    def _validar_cnpj(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validar_cnpj(v)

    @field_validator("cpf")
    @classmethod
    def _validar_cpf(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.isdigit() or len(v) != 11:
            raise ValueError("CPF deve ter exatamente 11 dígitos numéricos")
        return v

    @field_validator("chave")
    @classmethod
    def _validar_chave(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validar_chave_acesso(v)

    @model_validator(mode="after")
    def _validar_documento(self) -> DistribuicaoRequest:
        if bool(self.cnpj) == bool(self.cpf):
            raise ValueError("informe exatamente um entre cnpj e cpf")
        return self


class DistribuicaoResponse(BaseModel):
    """Resposta da distribuição de DF-e."""

    tipo: str
    cstat: str
    xmotivo: str
    ult_nsu: str | None = None
    max_nsu: str | None = None
    documentos: list[dict] | None = None
    xml_raw: str | None = None


class CadastroResponse(BaseModel):
    """Resposta da consulta de cadastro de contribuinte (CadConsultaCadastro4)."""

    uf: str = Field(min_length=2, max_length=2)
    documento: str
    tipo_documento: str
    cstat: str
    xmotivo: str
    contribuintes: list[dict] | None = None
    xml_raw: str | None = None


class OperacaoNaoRealizadaRequest(BaseModel):
    """Requisição do evento de operação não realizada (110112)."""

    chave_acesso: str
    justificativa: str = Field(min_length=15, max_length=255)

    @field_validator("chave_acesso")
    @classmethod
    def _validar_chave_acesso(cls, v: str) -> str:
        return validar_chave_acesso(v)
