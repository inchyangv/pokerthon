"""Playground helper APIs — signature generation and proxy."""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.signature import (
    build_canonical_query_string,
    build_canonical_string,
    compute_signature,
    sha256_hex,
)

router = APIRouter(prefix="/playground/api", tags=["playground"])


class SignRequest(BaseModel):
    secret_key: str
    method: str = "GET"
    path: str = "/v1/private/me"
    query_params: dict[str, str] = {}
    body: str = ""


class ProxyRequest(BaseModel):
    api_key: str
    secret_key: str
    method: str = "GET"
    path: str = "/v1/private/me"
    query_params: dict[str, str] = {}
    body: str | None = None


@router.post("/sign")
async def sign_endpoint(payload: SignRequest) -> dict[str, Any]:
    signing_key = sha256_hex(payload.secret_key.encode())
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    qs = build_canonical_query_string(payload.query_params)
    body_bytes = payload.body.encode() if payload.body else b""
    body_hash = sha256_hex(body_bytes)
    canonical = build_canonical_string(
        timestamp, nonce, payload.method.upper(), payload.path, qs, body_bytes
    )
    signature = compute_signature(signing_key, canonical)

    return {
        "headers": {
            "X-API-KEY": "(API Key를 직접 입력하세요)",
            "X-TIMESTAMP": timestamp,
            "X-NONCE": nonce,
            "X-SIGNATURE": signature,
        },
        "debug": {
            "body_hash": body_hash,
            "signing_key": signing_key,
            "canonical_string": canonical,
        },
    }


@router.post("/proxy")
async def proxy_endpoint(payload: ProxyRequest, request: Request) -> dict[str, Any]:
    signing_key = sha256_hex(payload.secret_key.encode())
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    qs = build_canonical_query_string(payload.query_params)
    body_bytes = payload.body.encode() if payload.body else b""
    body_hash = sha256_hex(body_bytes)
    canonical = build_canonical_string(
        timestamp, nonce, payload.method.upper(), payload.path, qs, body_bytes
    )
    signature = compute_signature(signing_key, canonical)

    auth_headers: dict[str, str] = {
        "X-API-KEY": payload.api_key,
        "X-TIMESTAMP": timestamp,
        "X-NONCE": nonce,
        "X-SIGNATURE": signature,
    }

    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}{payload.path}"
    if qs:
        url = f"{url}?{qs}"

    request_debug = {
        "canonical_string": canonical,
        "signing_key": signing_key,
        "body_hash": body_hash,
    }

    try:
        req_kwargs: dict[str, Any] = {
            "method": payload.method.upper(),
            "url": url,
            "headers": auth_headers,
        }
        if body_bytes and payload.method.upper() in ("POST", "PUT", "PATCH"):
            req_kwargs["content"] = body_bytes
            req_kwargs["headers"] = {**auth_headers, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(**req_kwargs)

        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text

        return {
            "status_code": resp.status_code,
            "headers": auth_headers,
            "request_debug": request_debug,
            "response_body": response_body,
        }

    except Exception as exc:
        return {
            "status_code": 0,
            "error": str(exc),
            "headers": auth_headers,
            "request_debug": request_debug,
            "response_body": None,
        }
