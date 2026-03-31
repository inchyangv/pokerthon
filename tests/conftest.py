import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as _db_module
from app.database import Base, get_session
from app.main import app


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    db_file = tmp_path / f"test_{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    # Patch module-level async_session_factory so code that bypasses DI
    # (e.g. game_state._fetch_seats_and_nicknames) also uses the test DB.
    original_factory = _db_module.async_session_factory
    _db_module.async_session_factory = factory

    # Also patch the imported reference inside game_state module and clear caches
    from app.api.public import game_state as _gs
    original_gs_factory = getattr(_gs, 'async_session_factory', None)
    _gs.async_session_factory = factory
    _gs._table_id_cache.clear()
    _gs._state_cache.clear()

    # Clear rate-limit and session state between tests
    from app.middleware.rate_limit import _clear_buckets
    from app.api.admin.views import _active_sessions
    from app.services.leaderboard_service import invalidate_leaderboard_cache
    _clear_buckets()
    _active_sessions.clear()
    invalidate_leaderboard_cache()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    _db_module.async_session_factory = original_factory
    if original_gs_factory is not None:
        _gs.async_session_factory = original_gs_factory
