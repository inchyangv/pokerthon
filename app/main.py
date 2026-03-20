from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin.accounts import router as admin_accounts_router
from app.api.health import router as health_router
from app.middleware.admin_auth import AdminAuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup hooks will be added in later milestones
    yield
    # shutdown


app = FastAPI(
    title="Pokerthon",
    description="Multi-table Texas Hold'em platform for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(AdminAuthMiddleware)

app.include_router(health_router)
app.include_router(admin_accounts_router)
