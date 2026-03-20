"""
In-memory sliding-window rate limiter (ASGI middleware).

Limits:
  /v1/private/*  →  15 req/min  keyed by X-API-KEY header
  /v1/public/*   →  60 req/min  keyed by client IP

No external dependency required (asyncio single-threaded event loop
guarantees that the deque accesses are safe without locking).
"""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque

PRIVATE_LIMIT = 15   # requests per window
PUBLIC_LIMIT = 60
WINDOW = 60.0        # seconds

# Global sliding-window buckets: rl_key → deque[monotonic timestamp]
_buckets: dict[str, deque[float]] = defaultdict(deque)


def _check(key: str, limit: int) -> tuple[bool, int]:
    """Sliding window check. Returns (allowed, remaining_after_this_request)."""
    now = time.monotonic()
    cutoff = now - WINDOW
    bucket = _buckets[key]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        return False, 0
    bucket.append(now)
    return True, limit - len(bucket)


def _clear_buckets() -> None:
    """Test helper: reset all rate-limit state."""
    _buckets.clear()


class RateLimitMiddleware:
    """Apply rate limiting to /v1/private/* and /v1/public/* routes."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        if path.startswith("/v1/private/"):
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            api_key = headers.get(b"x-api-key", b"").decode("latin-1")
            client = scope.get("client")
            fallback = client[0] if client else "unknown"
            rl_key = f"priv:{api_key or fallback}"
            limit = PRIVATE_LIMIT

        elif path.startswith("/v1/public/"):
            client = scope.get("client")
            ip = client[0] if client else "unknown"
            rl_key = f"pub:{ip}"
            limit = PUBLIC_LIMIT

        else:
            await self.app(scope, receive, send)
            return

        allowed, remaining = _check(rl_key, limit)

        if not allowed:
            body = json.dumps({
                "error": {
                    "code": "RATE_LIMITED",
                    "message": f"Too many requests. Limit: {limit}/min",
                }
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"x-ratelimit-limit", str(limit).encode()],
                    [b"x-ratelimit-remaining", b"0"],
                    [b"retry-after", b"60"],
                ],
            })
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return

        # Inject rate-limit headers into the normal response
        async def patched_send(event: dict) -> None:
            if event["type"] == "http.response.start":
                headers = list(event.get("headers", []))
                headers += [
                    [b"x-ratelimit-limit", str(limit).encode()],
                    [b"x-ratelimit-remaining", str(remaining).encode()],
                ]
                event = {**event, "headers": headers}
            await send(event)

        await self.app(scope, receive, patched_send)
