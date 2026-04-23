from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import init_db, session_scope
from app.routers.api_foods import router as foods_api_router
from app.routers.api_logs import router as logs_api_router
from app.routers.api_resolution import router as resolution_api_router
from app.routers.api_summary import router as summary_api_router
from app.routers.web import router as web_router
from app.routers.web import templates
from app.services.food_service import seed_demo_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as session:
        seed_demo_data(session)
    yield


settings = get_settings()
app = FastAPI(title=settings.project_name, lifespan=lifespan)
templates.env.globals["today_iso"] = lambda: date.today().isoformat()
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(web_router)
app.include_router(foods_api_router)
app.include_router(logs_api_router)
app.include_router(resolution_api_router)
app.include_router(summary_api_router)
