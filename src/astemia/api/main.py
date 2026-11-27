"""ASGI entry point: uvicorn astemia.api.main:app"""

from astemia.api.app import create_app

app = create_app()
