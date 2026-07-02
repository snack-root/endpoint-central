"""
Main FastAPI application — web dashboard on port 8000.
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.session import engine, Base
from app.db.redis_client import close_redis

# Routers
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.devices import router as devices_router
from app.api.v1.endpoints.domains_groups import router as dg_router
from app.api.v1.endpoints.management import router as mgmt_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables (alembic handles migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed initial admin
    from app.db.session import AsyncSessionLocal
    from app.services.auth_service import AuthService
    async with AsyncSessionLocal() as session:
        svc = AuthService(session)
        await svc.ensure_admin_exists()
        await session.commit()

    log.info("startup_complete", app=settings.APP_NAME)
    yield
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router,    tags=["auth"])
app.include_router(dashboard_router, tags=["dashboard"])
app.include_router(devices_router, tags=["devices"])
app.include_router(dg_router,      tags=["domains-groups"])
app.include_router(mgmt_router,    tags=["management"])


@app.get("/")
async def root():
    return RedirectResponse("/dashboard")


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return RedirectResponse("/login")
