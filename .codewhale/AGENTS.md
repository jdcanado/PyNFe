# CodeWhale — Regras do Projeto PyNFe

## Pré-commit obrigatório (não pular)

Antes de **qualquer commit**, execute nesta ordem e **só faça o commit se tudo passar**:

```bash
# 1. Formatação — verifica se o código está formatado (não altera arquivos)
.venv/bin/ruff format --check .

# 2. Lint — verifica erros estáticos
.venv/bin/ruff check .

# 3. Testes (recomendado antes de merge/push)
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_nfse_serializacao.py --ignore=tests/test_nfse_serializacao_betha.py --ignore=tests/test_nfse_serializacao_ginfes.py
```

- Se `ruff format --check .` falhar, rode `.venv/bin/ruff format .` para formatar e revise o diff.
- Se `ruff check .` falhar, corrija os erros (use `.venv/bin/ruff check --fix` apenas para fixes seguros).
- **Nunca commite com format/lint vermelhos** — o CI (`.github/workflows/ci.yml`) roda exatamente esses checks e rejeitará.

## Git hooks

O repositório versiona hooks em `.githooks/` (incluindo `pre-commit`). Ative em um clone novo:

```bash
git config core.hooksPath .githooks
```

O hook `pre-commit` roda `ruff format --check .` e `ruff check .` automaticamente e bloqueia o commit em caso de falha.

## Ambiente

- Python: `.venv/bin/` (dependências de dev instaladas)
- Versão do ruff: a do `requirements-dev.txt` (sem pin; manter compatível com o CI)
- Projeto suporta Python >= 3.9 (CI testa 3.9–3.13)
