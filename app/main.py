from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin.accounts import router as admin_accounts_router
from app.api.admin.chips import router as admin_chips_router
from app.api.admin.tables import router as admin_tables_router
from app.api.private.me import router as private_me_router
from app.api.private.tables import router as private_tables_router
from app.api.public.tables import router as public_tables_router
from app.api.admin.credentials import router as admin_credentials_router
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
app.include_router(admin_credentials_router)
app.include_router(admin_chips_router)
app.include_router(admin_tables_router)
app.include_router(private_tables_router)
app.include_router(private_me_router)
app.include_router(public_tables_router)
