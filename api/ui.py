"""Minimal same-origin pages for the Hermes session API."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_UI_ROOT = Path(__file__).resolve().parents[1] / "ui"
_NO_STORE = {"Cache-Control": "no-store"}


def install_ui(app: FastAPI) -> None:
    @app.get("/login", include_in_schema=False)
    async def login_page():
        return FileResponse(
            _UI_ROOT / "login.html",
            media_type="text/html",
            headers=_NO_STORE,
        )

    @app.get("/app", include_in_schema=False)
    async def chat_page():
        return FileResponse(
            _UI_ROOT / "chat.html",
            media_type="text/html",
            headers=_NO_STORE,
        )

    app.mount(
        "/static",
        StaticFiles(directory=_UI_ROOT / "static"),
        name="hermes-static",
    )
