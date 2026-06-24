"""FastAPI entrypoints for the local workbench."""

from .server import app, create_app

__all__ = ["app", "create_app"]
