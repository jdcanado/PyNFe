"""Schemas de NFC-e (modelo 65): emissão e resposta."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.schemas.nota_item import ClienteSchema, EmitenteSchema, PagamentoSchema, ProdutoItemSchema


class NFCeEmitirRequest(BaseModel):
    """Requisição de emissão de NFC-e (consumo, modelo 65).

    NFC-e não exige destinatário completo: `cliente` é opcional (apenas CPF
    quando informado).
    """

    empresa_id: UUID
    uf: str
    municipio: str
    natureza_operacao: str = "VENDA"
    data_emissao: datetime | None = None
    serie: str = "1"
    numero: str
    indicador_presencial: int = Field(default=1, ge=0, le=5)
    tipo_impressao_danfe: int = Field(default=4, ge=0, le=4)
    emitente: EmitenteSchema
    cliente: ClienteSchema | None = None
    produtos: list[ProdutoItemSchema]
    pagamentos: list[PagamentoSchema] = Field(default_factory=list)

    @field_validator("uf")
    @classmethod
    def _validar_uf(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha():
            raise ValueError("UF deve ter exatamente 2 letras")
        return v.upper()

    @field_validator("numero")
    @classmethod
    def _validar_numero(cls, v: str) -> str:
        if not v.isdigit() or not (1 <= int(v) <= 999_999_999):
            raise ValueError("numero deve ser numérico entre 1 e 999999999")
        return v


class NFCeResponse(BaseModel):
    """Resposta da emissão/consulta de NFC-e."""

    id: UUID | None = None
    empresa_id: UUID
    chave_acesso: str = Field(min_length=44, max_length=44)
    numero: int
    serie: int
    modelo: str = "65"
    status: str
    protocolo: str | None = None
    valor_total: float | None = None
    qrcode_url: str | None = None
    emitida_em: datetime | None = None
    autorizada_em: datetime | None = None
    xml_assinado: str | None = None
    xml_protocolado: str | None = None
    mensagem: str | None = None
