"""Configurações centrais da API PyNFe via Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configurações da API lidas de variáveis de ambiente."""

    app_name: str = "PyNFe API"
    version: str = "1.0.0"
    debug: bool = False

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

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância única (cacheada) de Settings."""
    return Settings()
