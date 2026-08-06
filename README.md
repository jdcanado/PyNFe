## PyNFe

[![Active Development](https://img.shields.io/badge/Maintenance%20Level-Actively%20Developed-brightgreen.svg)](https://gist.github.com/cheerfulstoic/d107229326a01ff0f333a1d3476e068d)
![status](https://img.shields.io/badge/status-stable-green.svg) ![https://github.com/TadaSoftware/PyNFe/actions](https://github.com/TadaSoftware/PyNFe/actions/workflows/ci.yml/badge.svg) ![pyversions](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
[![PyPI version](https://badge.fury.io/py/pynfe.svg)](https://badge.fury.io/py/pynfe)




Biblioteca de interface com os webservices de Nota Fiscal Eletrônica (NF-e) e Nota Fiscal de Consumidor Eletrônica (NFC-e) da SEFAZ e Receita Federal do Brasil, Nota Fiscal de Serviço Eletrônica (NFS-e) para Prefeituras e Manifesto de Documentos Fiscais Eletrônicos (MDF-e).

- **NF-e** visa substituir as notas fiscais séries 1 e 1A.
- **NFC-e** visa substituir as notas fiscais modelo 2 e cupom fiscal emitido por ECF.
- **NFS-e** padrão Abrasf para autorizadores Ginfes e Betha.
- **MDF-e** no padrão nacional deverá ser emitido obrigatoriamente no transporte de mercadoria intermunicipais por empresas prestadoras de serviço de transporte ou pelas demais empresas cujo transporte seja realizado em veículos próprios, arrendados ou transportador autônomo.


Características
------------

* NF-e e NFCe:
    * Atualizado para a versão 4.00
    * Modelo de Documento fiscal 55 e 65
    * Configuração para utilização em ambiente de produção e homologação (testes)
    * Emissão de notas fiscais normal e em contingência
    * Consulta Status do Serviço
    * Consultar Cadastro de contribuiente
    * Consultar nota fiscal pela chave de acesso
    * Consultar protocolo
    * Evento de cancelamento de notas
    * Evento de carta de correção
    * Evento de inutilizar de notas
    * Evento de manifestação do destinatário
    * Consultar Distribuição DF-e

* NFS-e:
    * Emissão de nota fiscal de serviço eletrônico
    * Consultar pelo número da NFS-e
    * Consultar por RPS (recibo provisório de serviço)
    * Consultar Lote
    * Cancelar NFS-e

* MDF-e:
    * Atualizado para a versão 3.00
    * Modelo de Documento 58
    * Emissão de Manifesto
    * Consultar Status do Serviço
    * Consultar MDF-e pela chave de acesso
    * Consultar MDF-es não encerrados
    * Consultar Recibo
    * Evento de Cancelamento
    * Evento de Encerramento de viagem
    * Evento de Inclusão de Condutor
    * Evento de Inclusão de DF-e
    * Evento de Pagamento DF-e

* CT-e:
    * Atualizado para a versão 3.00
    * Consultar Distribuição DF-e para CT-e
    * Emissão (A fazer)
    * Inutilização (A fazer)
    * Consultar CT-e pela chave de acesso (A fazer)
    * Consultar Status do Serviço (A fazer)
    * Eventos relacionados a CT-e (A fazer)

Dependências
------------

- lxml
  - Biblioteca de leitura e gravação de arquivos XML, de alta performance e fácil de implementar.
- signxml
  - Assinatura e validação do XML
- pyopenssl
  - Biblioteca para manuseio do certificado digital
- requests
  - Biblioteca para a comunicação com os webservices da SEFAZ
- suds-community (*apenas para NFS-e)
  - Biblioteca para a comunicação com os webservices via wsdl
- PyXB-X (*apenas para NFS-e)
  - Biblioteca para geração de bindings a partir de XML Schema(xsd)
- brazilfiscalreport (*apenas para Impressão)
  - Biblioteca para impressão de DANFE e DAMDFE

Referências
-----------

- Sites oficiais:
  - NFe: http://www.nfe.fazenda.gov.br/
  - MDF-e: https://dfe-portal.svrs.rs.gov.br/mdfe

- lxml
  - http://lxml.de/

- requests
  - http://docs.python-requests.org/en/latest/
  - https://github.com/psf/requests
  - https://pypi.python.org/pypi/requests

- Schemas para validação dos arquivos
  - NFe: http://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=BMPFMBoln3w=
  - MDFe: https://dfe-portal.svrs.rs.gov.br/Mdfe/Documentos

- Validador de XML
  - NFe: https://www.sefaz.rs.gov.br/NFE/NFE-VAL.aspx
  - MDFe: https://dfe-portal.svrs.rs.gov.br/MDFE/ValidadorXML

- Validador de assinaturas
  - https://servicos.receita.fazenda.gov.br/servicos/assinadoc/ValidadorAssinaturas.app/valida.aspx

- Impressão de Documentos Fiscais
  - https://github.com/Engenere/BrazilFiscalReport
  - https://engenere.github.io/BrazilFiscalReport


Instalação
-----------

* Instalar a versão estável: `pip install pynfe`

* Instalar as dependências da NFSe: `pip install 'pynfe[nfse]'`

* Instalar as dependências para Impressão: `pip install 'pynfe[impressao]'`

* Instalar versão de desenvolvimento:
```sh
pip install https://github.com/TadaSoftware/PyNFe/archive/refs/heads/main.zip
```

* Opcional para NFS-e:
```sh
pip install --user -r https://github.com/TadaSoftware/PyNFe/blob/main/requirements-nfse.txt
```


Exemplos de uso
-----------
  - Consulta Status

```python
from pynfe.processamento.comunicacao import ComunicacaoSefaz

certificado = "/home/user/certificado.pfx"
senha = "senha"
uf = "pr"
homologacao = True

con = ComunicacaoSefaz(uf, certificado, senha, homologacao)
xml = con.status_servico("nfe")
print(xml.text)
```

  Mais exemplos no [Wiki](https://github.com/TadaSoftware/PyNFe/wiki)


API REST (FastAPI)
-----------

A API REST fica no diretório `api/` e é servida pelo FastAPI. Para subir em desenvolvimento:

```sh
cp api/.env.example api/.env
```

Variáveis obrigatórias: `DATABASE_URL`, `KV_URL`, `KV_TOKEN`, `BLOB_READ_WRITE_TOKEN`, `JWT_SECRET` e `FERNET_KEY` (chave Fernet de 32 bytes em base64). Para gerar a chave Fernet:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Depois, suba a API:

```sh
uvicorn api.main:app --reload
```

Base URL local: `http://localhost:8000/api/v1` (os exemplos abaixo já incluem o prefixo).

Endpoints disponíveis:

- `GET  /api/v1/health` — health check
- `POST /api/v1/auth/token` — gera JWT (headers `api-key` e `api-secret`)
- `POST /api/v1/auth/refresh` — renova JWT (header `Authorization: Bearer`)
- `POST /api/v1/empresa/certificado` — upload do certificado A1 (PFX, multipart)
- `POST /api/v1/nfe/emitir` — emite NF-e (serializa, assina, envia à SEFAZ e persiste)

### Health check

`GET /api/v1/health`

```sh
curl http://localhost:8000/api/v1/health
```

Resposta:

```json
{"status": "ok", "version": "1.0.0"}
```

### Autenticação — obter token

`POST /api/v1/auth/token`

Gera um JWT a partir das credenciais do API client, enviadas nos headers `api-key` e `api-secret`.

```sh
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "api-key: <hash-da-api-key>" \
  -H "api-secret: <segredo-da-api-key>"
```

> Nota: o endpoint compara o header `api-key` com o hash armazenado em `api_clients.api_key_hash`.

Resposta (200):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "api_key_prefix": "teste01"
}
```

### Autenticação — renovar token

`POST /api/v1/auth/refresh`

Renova o JWT a partir de um token ainda válido.

```sh
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Authorization: Bearer <jwt>"
```

### Empresa — upload de certificado

`POST /api/v1/empresa/certificado`

Envia o certificado digital A1 (PFX) em `multipart/form-data`. O PFX é criptografado (Fernet) e enviado ao Vercel Blob; os PEMs são cacheados no KV (TTL 1h) e os metadados persistidos no banco.

```sh
curl -X POST http://localhost:8000/api/v1/empresa/certificado \
  -F "empresa_id=<uuid-da-empresa>" \
  -F "senha=<senha-do-pfx>" \
  -F "arquivo=@certificado.pfx"
```

Resposta (200):

```json
{
  "empresa_id": "3f2a1c6e-1111-2222-3333-444444444444",
  "cnpj": "99999999000199",
  "razao_social": "Empresa Teste LTDA",
  "certificado_nome_arquivo": "certificados/3f2a1c6e-1111-2222-3333-444444444444.pfx",
  "validade": "2027-08-05T12:00:00Z",
  "mensagem": "Certificado enviado com sucesso"
}
```

### NF-e — emissão

`POST /api/v1/nfe/emitir`

Recebe o payload completo da NF-e (schemas Pydantic), monta as entidades PyNFe via adapter, serializa o XML, assina em memória (PEMs), envia à SEFAZ e persiste o resultado.

```sh
curl -X POST http://localhost:8000/api/v1/nfe/emitir \
  -H "Content-Type: application/json" \
  -d '{
    "empresa_id": "00000000-0000-0000-0000-000000000001",
    "uf": "PR",
    "municipio": "4118402",
    "natureza_operacao": "VENDA",
    "tipo_documento": 1,
    "data_emissao": "2026-08-05T12:00:00Z",
    "modelo": 55,
    "serie": "1",
    "numero": "111",
    "forma_emissao": "1",
    "finalidade_emissao": "1",
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
    "cliente": {
      "razao_social": "JOSE DA SILVA",
      "tipo_documento": "CPF",
      "numero_documento": "12345678900",
      "indicador_ie": 9,
      "endereco_logradouro": "Rua dos Bobos",
      "endereco_numero": "Zero",
      "endereco_bairro": "Aquele Mesmo",
      "endereco_uf": "DF",
      "endereco_municipio": "Brasilia",
      "endereco_cep": "12345123"
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
        "icms": {
          "modalidade": "00",
          "origem": 0,
          "valor_base_calculo": "117.00",
          "aliquota": "18.00",
          "valor": "21.06"
        },
        "pis": {
          "situacao_tributaria": "01",
          "valor_base_calculo": "117.00",
          "aliquota_percentual": "0.65",
          "valor": "0.76"
        },
        "cofins": {
          "situacao_tributaria": "01",
          "valor_base_calculo": "117.00",
          "aliquota_percentual": "3.00",
          "valor": "3.51"
        }
      }
    ],
    "pagamentos": [
      {"forma_pagamento": "01", "valor": "117.00"}
    ]
  }'
```

Resposta (200, autorizada):

```json
{
  "id": "3f2a1c6e-1111-2222-3333-444444444444",
  "empresa_id": "00000000-0000-0000-0000-000000000001",
  "chave_acesso": "41260899999999000199550010000001118253639001",
  "numero": 111,
  "serie": 1,
  "modelo": "55",
  "status": "AUTORIZADA",
  "protocolo": "351111111111111",
  "valor_total": 117.0,
  "emitida_em": "2026-08-05T12:00:00Z",
  "autorizada_em": "2026-08-05T12:01:00Z",
  "xml_assinado": "<NFe ...>...</NFe>",
  "xml_protocolado": "<nfeProc ...>...</nfeProc>",
  "mensagem": null
}
```

Em caso de falha de comunicação com a SEFAZ, o `status` retorna `"ERRO"` com a mensagem em `mensagem`. Payloads com validação inválida retornam `422`; empresa sem certificado cadastrado retorna `400`.


Testes
-----------

```sh
python -m unittest
```

Lint
-----------

* Instalação: `pip install ruff`
* Checar lint: `ruff check .`
* Formatar: `ruff format .`


Bindings XSD
-----------

Para atualizar os bindings XSD da NFSe, execute o script `gerarnfsebindings.sh`.


Documentação
-----------
- https://github.com/TadaSoftware/PyNFe/wiki


Suporte
-----------
Se tiver qualquer problema or sugestão abra uma issue [aqui](https://github.com/TadaSoftware/PyNFe/issues) ou inicie uma discussão sobre um assunto [aqui](https://github.com/TadaSoftware/PyNFe/discussions).


Quem utiliza PyNFe
-----------
Lista de empresas/projetos que utilizam a lib PyNFe 
- Link da lista [aqui](https://github.com/TadaSoftware/PyNFe/wiki/Quem-utiliza-PyNFe).
- Sinta-se livre para incluir o nome da empresa/projeto na lista.


Licença
-----------
PyNFe é licenciada sob a [LGPL-3.0](LICENSE).
