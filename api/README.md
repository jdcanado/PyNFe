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

### Criar empresa (somente admin)

Cria a empresa + API client (plano free) e retorna as credenciais **uma única
vez**. O CSC/CSC ID da NFC-e podem ser informados já na criação (opcionais).

```bash
curl -X POST https://api.pynfe.com.br/api/v1/admin/empresa \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "cnpj": "99999999000199",
    "razao_social": "Empresa Teste LTDA",
    "nome_fantasia": "Teste",
    "inscricao_estadual": "9999999999",
    "uf": "PR",
    "csc": "0123456789abcdef0123456789abcdef0123",
    "csc_id": "000001",
    "client_name": "Client da Empresa"
  }'
```

Resposta (guarde `api_key` e `api_secret`, não serão exibidos de novo):

```json
{
  "empresa_id": "uuid-da-empresa",
  "cnpj": "99999999000199",
  "razao_social": "Empresa Teste LTDA",
  "api_key": "pnf_ab12",
  "api_secret": "...",
  "api_key_prefix": "pnf_ab12",
  "csc_id": "000001",
  "csc_mascarado": "0123****",
  "mensagem": "Empresa criada com sucesso. Guarde api_key e api_secret: não serão exibidos novamente."
}
```

Use o par (`api_key`, `api_secret`) no `POST /api/v1/auth/token` para gerar o
JWT da nova empresa. Exige um token de um API client com plano `admin`
(403 caso contrário; 409 se o CNPJ já existir).

### Atualizar empresa (PUT)

Atualiza dados da própria empresa (a do token autenticado). Campos parciais:
apenas os enviados são alterados. Útil para cadastrar o CSC da NFC-e
posteriormente à criação.

```bash
curl -X PUT https://api.pynfe.com.br/api/v1/empresa \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "nome_fantasia": "Fantasia Nova",
    "uf": "PR",
    "csc": "0123456789abcdef0123456789abcdef0123",
    "csc_id": "000001"
  }'
```

Resposta (o CSC completo nunca é retornado — apenas mascarado):

```json
{
  "empresa_id": "uuid-da-empresa",
  "cnpj": "99999999000199",
  "razao_social": "Empresa Teste LTDA",
  "nome_fantasia": "Fantasia Nova",
  "inscricao_estadual": "9999999999",
  "uf": "PR",
  "csc_id": "000001",
  "csc_mascarado": "0123****",
  "mensagem": "Empresa atualizada com sucesso"
}
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

## Deploy na Vercel

O projeto usa o Vercel CLI via GitHub Actions (`vercel deploy --prod --yes`).
O `vercel.json` na raiz configura rewrites, headers e os cron jobs.

### 1. Configurar secrets no Vercel

As variáveis de ambiente **não** ficam no repositório — configure no
dashboard da Vercel (Project → Settings → Environment Variables), ou via
CLI:

```bash
vercel env add DATABASE_URL production
vercel env add KV_URL production
vercel env add KV_TOKEN production
vercel env add BLOB_READ_WRITE_TOKEN production
vercel env add JWT_SECRET production
vercel env add FERNET_KEY production
vercel env add WEBHOOK_URL production
```

Repita para os ambientes `preview` e `development` quando necessário.

### 2. Secrets no GitHub Environments

O workflow `deploy-production.yml` usa os seguintes secrets do GitHub
(Organization/Repository secrets ou Environment secrets):

| Secret | Descrição |
|---|---|
| `VERCEL_TOKEN` | Token de acesso do Vercel (Account → Settings → Tokens) |
| `VERCEL_ORG_ID` | ID da organização Vercel |
| `VERCEL_PROJECT_ID` | ID do projeto Vercel (Project → Settings → General) |

Exemplo de configuração:

```bash
gh secret set VERCEL_TOKEN --env production
gh secret set VERCEL_ORG_ID --env production
gh secret set VERCEL_PROJECT_ID --env production
```

### 3. Conectar domínio customizado

No dashboard da Vercel (Project → Settings → Domains), adicione o domínio
(ex.: `api.pynfe.com.br`) e siga as instruções de DNS:

- **Registro CNAME**: `api.pynfe.com.br` → `cname.vercel-dns.com`
- Ou configure os **Name Servers** apontando para a Vercel (apex).

Após propagar o DNS, o domínio passa a servir o deploy de produção.

## Migração inicial do banco

As tabelas são criadas com `Base.metadata.create_all` (idempotente):

```bash
PYTHONPATH=. python api/scripts/migrate.py
```

Rode uma vez após o primeiro deploy (ou em cada ambiente novo) usando o
`DATABASE_URL` de produção.

## Seed de dados de teste (staging apenas)

O script `api/scripts/seed.py` insere uma empresa + API client de teste e é
**bloqueado fora do ambiente de staging** (exige `AMBIENTE=2`):

```bash
AMBIENTE=2 PYTHONPATH=. python api/scripts/seed.py
```

Variáveis opcionais: `SEED_CNPJ`, `SEED_RAZAO_SOCIAL`, `SEED_UF`,
`SEED_CLIENT_NAME`. O script imprime a API key gerada (guarde com segurança).

## Smoke test pós-deploy

Após o merge na `main` (deploy automático), verifique:

```bash
curl https://py-nfe.vercel.app/api/v1/health
# {"status":"ok","version":"1.0.0"}

curl -I https://py-nfe.vercel.app/docs
# HTTP 200 (Swagger UI)
```
