import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


_UI_PATHS = {"/admin/login", "/admin/logout"}
_SESSION_COOKIE = "admin_session"


def _has_valid_session(request: Request) -> bool:
    from app.api.admin.views import _active_sessions
    token = request.cookies.get(_SESSION_COOKIE)
    return token is not None and token in _active_sessions


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for static assets
        if path.startswith("/static"):
            return await call_next(request)

        if path.startswith("/admin"):
            # Login / logout pages are always accessible
            if path in _UI_PATHS:
                return await call_next(request)

            # Web UI requests (Accept: text/html or no Accept) use session cookie
            accept = request.headers.get("accept", "")
            if "text/html" in accept or (
                not request.headers.get("Authorization") and
                _has_valid_session(request)
            ):
                # Session cookie auth for web UI
                if _has_valid_session(request):
                    return await call_next(request)
                # Not authenticated via cookie — redirect to login
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url="/admin/login", status_code=302)

            # JSON API requests: if Bearer header is present, validate it
            auth = request.headers.get("Authorization", "")
            if auth:
                if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], settings.ADMIN_PASSWORD):
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing admin credentials"}},
                    )
                return await call_next(request)

            # No auth at all on a non-HTML request → 401 (API clients)
            # But for browser-like GET requests without auth → redirect to login
            if request.method == "GET":
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url="/admin/login", status_code=302)

            return JSONResponse(
                status_code=401,
                content={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing admin credentials"}},
            )

        return await call_next(request)
