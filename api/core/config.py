"""Configurações centrais da API PyNFe via Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Caminho do arquivo .env (api/.env) relativo a este módulo
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Configurações da API lidas de variáveis de ambiente.

    Lê também o arquivo `api/.env` (veja `api/.env.example`). Variáveis de
    ambiente reais têm precedência sobre o arquivo.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
    )

    app_name: str = "PyNFe API"
    version: str = "1.0.0"
    debug: bool = False

    # Rate limiting
    ratelimit_enabled: bool = True

    # Database
    database_url: str
    database_pool_size: int = 5

    # KV (Upstash Redis)
    kv_url: str
    kv_token: str

    # Vercel Blob
    blob_read_write_token: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    api_key_prefix: str = "pnf_"

    # Cryptografia
    fernet_key: str

    # SEFAZ
    sefaz_timeout: int = 28

    # Webhook (notificações de finalização de notas — vazio desativa)
    webhook_url: str = ""

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância única (cacheada) de Settings."""
    return Settings()
