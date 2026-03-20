from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown


app = FastAPI(
    title="Pokerthon",
    description="Multi-table Texas Hold'em platform for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)
