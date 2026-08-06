"""Serviços de domínio da API."""

from api.services.certificado_service import obter_pem, upload_certificado

__all__ = ["obter_pem", "upload_certificado"]
