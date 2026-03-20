import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.admin.accounts import router as admin_accounts_router
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
from app.middleware.admin_auth import AdminAuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    from app.bots.runner import bot_runner_loop
    from app.bots.seed import seed_bots
    from app.database import async_session_factory
    from app.services.recovery_service import recover_in_progress_hands
    from app.tasks.nonce_cleanup import nonce_cleanup_loop
    from app.tasks.timeout_checker import timeout_checker_loop

    async with async_session_factory() as session:
        await recover_in_progress_hands(session)

    try:
        async with async_session_factory() as session:
            await seed_bots(session)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Bot seed failed — continuing startup")

    timeout_task = asyncio.ensure_future(timeout_checker_loop())
    nonce_task = asyncio.ensure_future(nonce_cleanup_loop())
    bot_task = asyncio.ensure_future(bot_runner_loop())

    yield

    # --- Shutdown ---
    for task in (timeout_task, nonce_task, bot_task):
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

app.add_middleware(AdminAuthMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
