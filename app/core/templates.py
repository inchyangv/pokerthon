"""Shared Jinja2Templates instance with asset_url helper registered."""
import hashlib
from pathlib import Path

from fastapi.templating import Jinja2Templates


def _file_hash(path: str) -> str:
    try:
        return hashlib.md5(Path(path).read_bytes()).hexdigest()[:8]
    except OSError:
        return "00000000"


_ASSET_HASHES: dict[str, str] = {
    "/static/viewer.css": _file_hash("app/static/viewer.css"),
    "/static/admin.css": _file_hash("app/static/admin.css"),
    "/static/playground.css": _file_hash("app/static/playground.css"),
    "/static/playground.js": _file_hash("app/static/playground.js"),
}


def asset_url(path: str) -> str:
    h = _ASSET_HASHES.get(path)
    return f"{path}?v={h}" if h else path


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_url"] = asset_url
