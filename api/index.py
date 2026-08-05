"""Entrypoint Vercel Serverless."""

from api.main import create_app

app = create_app()
