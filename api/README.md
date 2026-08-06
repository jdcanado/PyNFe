# PyNFe API

API REST para emissão de NF-e, NFC-e e consulta GTIN, com comunicação direta
com a SEFAZ. Base: `https://api.pynfe.com.br` (homologação por padrão).

## Autenticação

Obtenha um token JWT com a sua API key:

```bash
# 1. Gere o token usando o par (api_key, secret) do seu API client
curl -X POST https://api.pynfe.com.br/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "SUA_API_KEY", "api_secret": "SEU_SECRET"}'
```

Use o token em todas as chamadas:

```bash
export TOKEN="<token_retornado>"
export AUTH="Authorization: Bearer $TOKEN"
```

## Exemplos

### Emitir NF-e (modelo 55)

```bash
curl -X POST https://api.pynfe.com.br/api/v1/nfe/emitir \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "empresa_id": "UUID_DA_EMPRESA",
    "uf": "PR",
    "municipio": "4118402",
    "natureza_operacao": "VENDA",
    "serie": "1",
    "numero": "111",
    "emitente": {
      "razao_social": "Empresa Teste LTDA",
      "cnpj": "99999999000199",
      "inscricao_estadual": "9999999999",
      "codigo_de_regime_tributario": "3",
      "endereco_logradouro": "Rua da Paz",
      "endereco_numero": "666",
      "endereco_bairro": "Sossego",
      "endereco_uf": "PR",
      "endereco_municipio": "Paranavaí",
      "endereco_cod_municipio": "4118402",
      "endereco_cep": "87704000"
    },
    "produtos": [
      {
        "codigo": "000328",
        "descricao": "Produto teste",
        "ncm": "99999999",
        "cfop": "5102",
        "ean": "1234567890121",
        "unidade_comercial": "UN",
        "quantidade_comercial": "12",
        "valor_unitario_comercial": "9.75",
        "valor_total_bruto": "117.00",
        "icms": {"modalidade": "00", "origem": 0, "valor_base_calculo": "117.00", "aliquota": "18.00", "valor": "21.06"}
      }
    ],
    "pagamentos": [{"forma_pagamento": "01", "valor": "117.00"}]
  }'
```

### Consultar NF-e / listar notas

```bash
curl "https://api.pynfe.com.br/api/v1/nfe/listar?page=1&size=20" -H "$AUTH"
```

### Cancelar NF-e (evento 110111)

```bash
curl -X POST https://api.pynfe.com.br/api/v1/nfe/cancelar \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "chave_acesso": "35111111111111111111111111111111111111111111",
    "justificativa": "Cancelamento por erro na emissão"
  }'
```

### Emitir NFC-e (modelo 65)

```bash
curl -X POST https://api.pynfe.com.br/api/v1/nfce/emitir \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "empresa_id": "UUID_DA_EMPRESA",
    "uf": "PR",
    "municipio": "4118402",
    "numero": "1",
    "serie": "1",
    "emitente": { "razao_social": "Empresa Teste LTDA", "cnpj": "99999999000199", "inscricao_estadual": "9999999999", "codigo_de_regime_tributario": "3", "endereco_logradouro": "Rua da Paz", "endereco_numero": "666", "endereco_bairro": "Sossego", "endereco_uf": "PR", "endereco_municipio": "Paranavaí", "endereco_cod_municipio": "4118402", "endereco_cep": "87704000" },
    "produtos": [
      { "codigo": "000328", "descricao": "Produto teste", "ncm": "99999999", "cfop": "5102", "ean": "1234567890121", "unidade_comercial": "UN", "quantidade_comercial": "1", "valor_unitario_comercial": "10.00", "valor_total_bruto": "10.00" }
    ],
    "pagamentos": [{"forma_pagamento": "01", "valor": "10.00"}]
  }'
```

### Consultar GTIN

```bash
curl https://api.pynfe.com.br/api/v1/gtin/consultar/7891234567890 -H "$AUTH"
```

### Status SEFAZ por UF

```bash
# Todas as UFs
curl https://api.pynfe.com.br/api/v1/sefaz/status -H "$AUTH"

# Uma UF específica
curl https://api.pynfe.com.br/api/v1/sefaz/status/SP -H "$AUTH"
```

## Documentação interativa

- Swagger UI: `https://api.pynfe.com.br/docs`
- OpenAPI JSON: `https://api.pynfe.com.br/openapi.json`
- Documentação completa: `docs.api.pynfe.com.br`
