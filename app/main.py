import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.admin.accounts import router as admin_accounts_router
from app.api.viewer.views import router as viewer_router
from app.api.admin.bots import router as admin_bots_router
from app.api.admin.chips import router as admin_chips_router
from app.api.admin.tables import router as admin_tables_router
from app.api.admin.views import router as admin_views_router
from app.api.private.action import router as private_action_router
from app.api.private.me import router as private_me_router
from app.api.private.state import router as private_state_router
from app.api.private.tables import router as private_tables_router
from app.api.public.game_state import router as public_game_state_router
from app.api.public.history import router as public_history_router
from app.api.public.leaderboard import router as public_leaderboard_router
from app.api.public.tables import router as public_tables_router
from app.api.admin.credentials import router as admin_credentials_router
from app.api.health import router as health_router
from app.api.playground.api import router as playground_api_router
from app.api.playground.views import router as playground_views_router
from app.middleware.admin_auth import AdminAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from starlette.middleware.gzip import GZipMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    from app.bots.runner import bot_runner_loop
    from app.bots.seed import seed_bots
    from app.database import async_session_factory
    from app.services.recovery_service import recover_in_progress_hands
    from app.tasks.keepalive import keepalive_loop
    from app.tasks.nonce_cleanup import nonce_cleanup_loop
    from app.tasks.timeout_checker import timeout_checker_loop

    async def _recover():
        async with async_session_factory() as session:
            await recover_in_progress_hands(session)

    async def _seed():
        try:
            async with async_session_factory() as session:
                await seed_bots(session)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Bot seed failed — continuing startup")

    # Run recovery and seeding in parallel to reduce startup latency
    await asyncio.gather(_recover(), _seed())

    timeout_task = asyncio.ensure_future(timeout_checker_loop())
    nonce_task = asyncio.ensure_future(nonce_cleanup_loop())
    bot_task = asyncio.ensure_future(bot_runner_loop())
    keepalive_task = asyncio.ensure_future(keepalive_loop())

    yield

    # --- Shutdown ---
    for task in (timeout_task, nonce_task, bot_task, keepalive_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Pokerthon",
    description="Multi-table Texas Hold'em platform for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(RateLimitMiddleware)  # outermost: runs before AdminAuth
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def _file_hash(path: str) -> str:
    """Return first 8 chars of MD5 hash for a static file."""
    try:
        return hashlib.md5(Path(path).read_bytes()).hexdigest()[:8]
    except OSError:
        return "00000000"


# Pre-compute content hashes at startup for fingerprinting
_ASSET_HASHES: dict[str, str] = {
    "/static/viewer.css": _file_hash("app/static/viewer.css"),
    "/static/admin.css":  _file_hash("app/static/admin.css"),
    "/static/playground.css": _file_hash("app/static/playground.css"),
    "/static/playground.js":  _file_hash("app/static/playground.js"),
}


def asset_url(path: str) -> str:
    """Return asset URL with content-hash query param for immutable caching."""
    h = _ASSET_HASHES.get(path)
    return f"{path}?v={h}" if h else path


# Register asset_url as a Jinja2 global so all templates can call it
_jinja = Jinja2Templates(directory="app/templates")
_jinja.env.globals["asset_url"] = asset_url


@app.middleware("http")
async def static_cache_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        if request.url.query:
            # Versioned request (e.g. ?v=abc123) → immutable 1-year cache
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # Unversioned → short cache with revalidation
            response.headers["Cache-Control"] = "public, max-age=3600"
    return response

app.include_router(admin_views_router)
app.include_router(health_router)
app.include_router(admin_accounts_router)
app.include_router(admin_bots_router)
app.include_router(admin_credentials_router)
app.include_router(admin_chips_router)
app.include_router(admin_tables_router)
app.include_router(private_tables_router)
app.include_router(private_action_router)
app.include_router(private_me_router)
app.include_router(private_state_router)
app.include_router(public_tables_router)
app.include_router(public_game_state_router)
app.include_router(public_history_router)
app.include_router(public_leaderboard_router)
app.include_router(viewer_router)
app.include_router(playground_api_router)
app.include_router(playground_views_router)
