"""Playground page routes."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

router = APIRouter(prefix="/playground", tags=["playground"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def explorer_page(request: Request):
    return templates.TemplateResponse(request, "playground/explorer.html", {})


@router.get("/signature", response_class=HTMLResponse)
async def signature_page(request: Request):
    return templates.TemplateResponse(request, "playground/signature.html", {})


@router.get("/quickstart", response_class=HTMLResponse)
async def quickstart_page(request: Request):
    return templates.TemplateResponse(request, "playground/quickstart.html", {})
