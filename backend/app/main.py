"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_db
from .jobs import jobs
from .models import User
from .realtime import hub
from .routers import expenses, groups, inventory, meta, plans, recognition, users
from .services import twin as twin_service
from .wiki import get_wiki

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mealagent")


async def weekly_twin_refresh() -> None:
    """Digital-twin update cycle: once a day, refresh any twin older than 7 days."""
    while True:
        try:
            db = SessionLocal()
            try:
                wiki = get_wiki()
                for user in db.query(User).all():
                    for m in user.memberships:
                        twin_service.ensure_fresh(db, user, m.group, wiki)
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("twin refresh failed")
        await asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    get_wiki()
    hub.bind_loop(asyncio.get_running_loop())
    jobs.resume_unfinished()
    task = asyncio.create_task(weekly_twin_refresh())
    log.info("MealAgent ready · LLM %s · wiki %s", "DeepSeek online" if settings.llm_online else "offline (rule engine)",
             settings.wiki_dir)
    yield
    task.cancel()


app = FastAPI(title="MealAgent API", version="3.1", lifespan=lifespan,
              description="AI 膳食统筹微信小程序后端：库存、记账、多智能体周计划、数字孪生")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (users.router, groups.router, inventory.router, recognition.router, expenses.router, plans.router, meta.router):
    app.include_router(r)
# pixel fonts for the mini program (loaded at runtime with wx.loadFontFace)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(ValueError)
async def value_error(_req: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

