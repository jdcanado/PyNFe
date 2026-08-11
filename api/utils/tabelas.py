"""Tabelas de referência carregadas de arquivos do repositório.

As tabelas (NCM, cClassTrib) ficam em `pynfe/data/` como arquivos e são
carregadas em memória no primeiro uso. Atualização = trocar o arquivo no
repositório e fazer o deploy (as instâncias são recriadas no cold start).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "pynfe" / "data"


@lru_cache(maxsize=1)
def carregar_ncms() -> frozenset[str]:
    """Carrega os códigos NCM vigentes (8 dígitos, sem pontuação)."""
    caminho = _DATA_DIR / "NCM" / "ncm.csv"
    codigos: set[str] = set()
    with caminho.open(encoding="utf-8") as f:
        next(f, None)  # cabeçalho
        for linha in f:
            codigo = linha.strip()
            if codigo:
                codigos.add(codigo)
    return frozenset(codigos)


def is_ncm_valido(codigo: str) -> bool:
    """True se o NCM (8 dígitos) existe na tabela vigente (rejeição 486)."""
    return codigo in carregar_ncms()


@lru_cache(maxsize=1)
def carregar_cclass_trib() -> frozenset[str]:
    """Carrega os códigos cClassTrib (6 dígitos) da classificação IBS/CBS.

    Retorna vazio se o arquivo ainda não existir no repositório (validação
    de existência fica desligada; apenas o formato é validado).
    """
    caminho = _DATA_DIR / "IBS" / "cclass_trib.csv"
    if not caminho.exists():
        return frozenset()
    codigos: set[str] = set()
    with caminho.open(encoding="utf-8") as f:
        next(f, None)  # cabeçalho
        for linha in f:
            codigo = linha.strip()
            if codigo:
                codigos.add(codigo)
    return frozenset(codigos)


def is_cclass_trib_valido(codigo: str) -> bool:
    """True se o cClassTrib existe na tabela; True se a tabela não existe."""
    tabela = carregar_cclass_trib()
    if not tabela:
        return True  # tabela ausente: valida apenas formato no schema
    return codigo in tabela
