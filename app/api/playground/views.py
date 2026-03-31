"""Playground page routes."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from app.core.templates import templates

router = APIRouter(prefix="/playground", tags=["playground"])


@router.get("/", response_class=HTMLResponse)
async def explorer_page(request: Request):
    return templates.TemplateResponse(request, "playground/explorer.html", {})


@router.get("/signature", response_class=HTMLResponse)
async def signature_page(request: Request):
    return templates.TemplateResponse(request, "playground/signature.html", {})


@router.get("/quickstart", response_class=HTMLResponse)
async def quickstart_page(request: Request):
    return templates.TemplateResponse(request, "playground/quickstart.html", {})
