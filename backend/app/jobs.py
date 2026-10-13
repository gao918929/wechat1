"""Background meal-plan generation with streamed progress.

Generation runs as a server-side task independent of the HTTP connection: if the user leaves the
page or the request times out, it keeps going, then sends an in-app notification (and a WeChat
subscription message when configured). Progress events are persisted, so a client can reconnect
to the SSE stream (or poll) and replay everything it missed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import select

from .agents.orchestrator import cache_key, run_plan
from .config import settings
from .db import SessionLocal
from .llm import LLMClient, new_client
from .models import Group, MealPlan, Notification, PlanCache, User
from .realtime import hub
from .services.planning import build_context
from .wechat import send_plan_ready
from .wiki import get_wiki

log = logging.getLogger("mealagent.jobs")
TERMINAL = ("done", "error")


class PlanJobs:
    def __init__(self) -> None:
        self.subscribers: dict[int, list[asyncio.Queue]] = {}
        self.tasks: dict[int, asyncio.Task] = {}
        self.llm_factory = new_client

    def start(self, plan_id: int) -> None:
        self.tasks[plan_id] = asyncio.get_running_loop().create_task(self._run(plan_id))

    async def wait(self, plan_id: int) -> None:
        task = self.tasks.get(plan_id)
        if task:
            await task

    async def _run(self, plan_id: int) -> None:
        db = SessionLocal()
        try:
            plan = db.get(MealPlan, plan_id)
            user, group = db.get(User, plan.created_by), db.get(Group, plan.group_id)
            plan.status, plan.events = "running", []
            db.commit()

            async def emit(event_type: str, data: dict) -> None:
                ev = {"seq": len(plan.events), "type": event_type, "data": data, "ts": round(time.time(), 3)}
                plan.events = plan.events + [ev]
                db.commit()
                for q in self.subscribers.get(plan_id, []):
                    q.put_nowait(ev)

            llm: LLMClient = self.llm_factory()
            wiki = get_wiki()
            ctx = await build_context(db, user, group, plan.instruction, plan.options or {}, llm, wiki, emit)
            key = cache_key(ctx)
            cached = db.get(PlanCache, key) if settings.plan_cache_enabled and plan.options.get("cache", True) else None
            if cached:
                result = dict(cached.result, cached=True)
                await emit("cached", {"message": "相同约束组合的方案已缓存，直接复用"})
                for v in result["variants"]:
                    await emit("variant", {"key": v["key"], "title": v["title"], "tradeoff": v["tradeoff"],
                                           "rank": v["rank"], "summary": v["summary"], "passed": v["validation"]["passed"]})
                top = result["variants"][0]
                for d in top["days"]:
                    await emit("day", {"variant": top["key"], "day": d})
                await emit("shopping", {"variant": top["key"], "shopping": top["shopping"]})
            else:
                result = await run_plan(ctx)
                if settings.plan_cache_enabled:
                    db.merge(PlanCache(key=key, result=result))
            plan.result, plan.status, plan.finished_at = result, "done", datetime.now()
            plan.chosen_variant = result["recommended"]
            title = f"{ctx.days}天{'/'.join({'breakfast': '早餐', 'lunch': '午餐', 'dinner': '晚餐'}[m] for m in ctx.meals)}计划已生成"
            db.add(Notification(user_id=user.id, title="膳食计划已完成", body=title, link=f"/pages/plan/plan?id={plan.id}"))
            db.commit()
            await emit("done", {"plan_id": plan.id, "recommended": result["recommended"], "mode": result["mode"]})
            hub.publish(group.id, "plan.ready", plan_id=plan.id, by=user.nickname)
            await send_plan_ready(user.openid, plan.id, title)
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            log.exception("plan %s failed", plan_id)
            db.rollback()
            plan = db.get(MealPlan, plan_id)
            if plan is not None:
                plan.status, plan.error, plan.finished_at = "failed", str(exc)[:500], datetime.now()
                ev = {"seq": len(plan.events or []), "type": "error", "data": {"message": str(exc)[:300]}, "ts": time.time()}
                plan.events = (plan.events or []) + [ev]
                db.add(Notification(user_id=plan.created_by, title="膳食计划生成失败", body=str(exc)[:200],
                                    link=f"/pages/plan/plan?id={plan.id}"))
                db.commit()
                for q in self.subscribers.get(plan_id, []):
                    q.put_nowait(ev)
        finally:
            db.close()
            self.tasks.pop(plan_id, None)

    async def stream(self, plan_id: int, since: int = 0) -> AsyncIterator[dict]:
        """Replay persisted events from ``since``, then follow live events until done/error."""
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(plan_id, []).append(q)
        try:
            db = SessionLocal()
            try:
                plan = db.get(MealPlan, plan_id)
                events, status = list(plan.events or []), plan.status
            finally:
                db.close()
            last = since - 1
            for ev in events:
                if ev["seq"] >= since:
                    last = ev["seq"]
                    yield ev
                    if ev["type"] in TERMINAL:
                        return
            if status in ("done", "failed"):
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "ping", "seq": last, "data": {}}
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
                if ev["type"] in TERMINAL:
                    return
        finally:
            self.subscribers.get(plan_id, []).remove(q)

    def resume_unfinished(self) -> None:
        """On startup, restart plans interrupted by a server restart."""
        db = SessionLocal()
        try:
            ids = db.scalars(select(MealPlan.id).where(MealPlan.status.in_(("pending", "running")))).all()
        finally:
            db.close()
        for pid in ids:
            self.start(pid)


jobs = PlanJobs()
