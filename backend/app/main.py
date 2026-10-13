import asyncio
import contextlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .config import ROOT, Settings
from .domain import DISCLAIMER, catalog, consume, freshness, known, nutrition, price_map, snapshot, target_for
from .orchestrator import Orchestrator
from .provider import DeepSeek, ProviderError
from .recognition import clean_image, recognize, calibrate, remember_correction
from .schemas import (Model, Profile, GroupCreate, GroupSettings, InventoryInput, ConsumptionRequest,
                      ReceiptConfirm, PlanRequest, MealInput, Feedback, TextInput, LoginInput,
                      DevLogin, InviteInput, Selection)
from .services import build_twin, confirm_draft, idempotent, receipt, record_meal
from .store import Store, digest, now, packed, uid


class PriceInput(Model):
    ingredient_id: str
    cents_per_kg: float = Field(gt=0, le=10000000)
    source: str = Field(min_length=2, max_length=200)


class TextDraft(Model):
    kind: Literal["inventory", "receipt", "meal"] = "inventory"
    text: str = Field(min_length=2, max_length=3000)


class InventoryConfirmation(Model):
    items: list[InventoryInput] = Field(min_length=1, max_length=100)


def create_app(settings=None, provider=None):
    settings = settings or Settings()
    store = Store(settings.db_path)
    provider = provider or DeepSeek(settings)
    orchestrator = Orchestrator(store, provider)

    @asynccontextmanager
    async def lifespan(app):
        orchestrator.recover()
        task = asyncio.create_task(orchestrator.worker()) if settings.worker_enabled else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="MealAgent", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.orchestrator = store, orchestrator
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])
    hits = defaultdict(deque)

    @app.middleware("http")
    async def limits(request, call_next):
        if request.url.path.startswith("/api/"):
            if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 7*1024*1024:
                return JSONResponse({"detail": "Request exceeds 7 MB"}, status_code=413)
            host = request.client.host if request.client else "unknown"
            bucket = host + (":ai" if any(w in request.url.path for w in ("/recognize", "/drafts/text", "/refine")) else ":general")
            queue, clock = hits[bucket], time.monotonic()
            while queue and queue[0] < clock-60:
                queue.popleft()
            limit = 10 if bucket.endswith(":ai") else 240
            if len(queue) >= limit:
                return JSONResponse({"detail": "Too many requests; wait a minute"}, status_code=429)
            queue.append(clock)
            if len(hits) > 2000:
                for key in list(hits):
                    if not hits[key] or hits[key][-1] < clock-60:
                        del hits[key]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    def authenticate(token):
        with store.tx() as db:
            row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires>?", (digest(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, "Session expired or invalid; sign in again")
        return row["user_id"]

    def user(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Sign in first")
        return authenticate(authorization[7:])

    User = Annotated[str, Depends(user)]

    def login(openid, name):
        token = secrets.token_urlsafe(40)
        with store.tx() as db:
            row = db.execute("SELECT id FROM users WHERE openid=?", (openid,)).fetchone()
            user_id = row["id"] if row else uid()
            if row is None:
                db.execute("INSERT INTO users(id,openid,name,profile) VALUES(?,?,?,?)",
                           (user_id, openid, name, packed(Profile().model_dump())))
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), user_id, time.time()+settings.session_days*86400))
        return {"token": token, "user_id": user_id, "expires_in": settings.session_days*86400}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "ai_configured": bool(settings.api_key), "dev_login": settings.allow_dev_login,
                "version": "0.1.0", "nutrition_source": "USDA FoodData Central SR Legacy", "disclaimer": DISCLAIMER}

    @app.post("/api/auth/dev")
    def dev_login(body: DevLogin, request: Request):
        if not settings.allow_dev_login or (request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient")):
            raise HTTPException(403, "Local development login is disabled")
        if not hmac.compare_digest(body.key, settings.dev_key):
            raise HTTPException(401, "Invalid development key")
        return login("dev:" + body.name, body.name)

    @app.post("/api/auth/wechat")
    async def wechat_login(body: LoginInput):
        if not settings.app_id or not settings.app_secret:
            raise HTTPException(503, "Configure WECHAT_APP_ID and WECHAT_APP_SECRET on the backend")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
                    "appid": settings.app_id, "secret": settings.app_secret, "js_code": body.code, "grant_type": "authorization_code"})
                result = resp.json()
            if resp.is_error or not result.get("openid"):
                raise HTTPException(401, "WeChat sign-in failed; get a fresh login code")
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "Unable to contact WeChat") from exc
        return login(result["openid"], body.name)

    @app.post("/api/auth/logout")
    def logout(who: User, authorization: Annotated[str, Header()]):
        with store.tx() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(authorization[7:]),))
        return {"ok": True}

    @app.get("/api/me")
    def me(who: User):
        with store.tx() as db:
            row = db.execute("SELECT id,name,profile FROM users WHERE id=?", (who,)).fetchone()
            return {"id": row["id"], "name": row["name"], "profile": json.loads(row["profile"])}

    @app.put("/api/me/profile")
    def update_profile(body: Profile, who: User):
        for fid in body.forbidden_ingredients:
            known(fid)
        with store.tx() as db:
            db.execute("UPDATE users SET profile=? WHERE id=?", (packed(body.model_dump()), who))
        return body

    @app.get("/api/me/target")
    def target(who: User):
        with store.tx() as db:
            profile = json.loads(db.execute("SELECT profile FROM users WHERE id=?", (who,)).fetchone()[0])
        return {"target": target_for(profile), "disclaimer": DISCLAIMER}

    @app.get("/api/catalog")
    def food_catalog(who: User):
        return list(catalog().values())

    @app.get("/api/groups")
    def groups(who: User):
        with store.tx() as db:
            return [{"id": r["id"], "name": r["name"], "role": r["role"], "settings": json.loads(r["settings"])}
                    for r in db.execute("SELECT g.*,m.role FROM groups g JOIN members m ON g.id=m.group_id WHERE m.user_id=?", (who,))]

    @app.post("/api/groups", status_code=201)
    def create_group(body: GroupCreate, who: User):
        key, code = uid(), secrets.token_urlsafe(24)
        config = GroupSettings(budget_cents=body.budget_cents, budget_mode=body.budget_mode).model_dump()
        with store.tx() as db:
            db.execute("INSERT INTO groups VALUES(?,?,?,?,?)", (key, who, body.name, digest(code), packed(config)))
            db.execute("INSERT INTO members VALUES(?,?,?)", (key, who, "admin"))
        return {"id": key, "name": body.name, "invite_code": code, "settings": config}

    @app.post("/api/groups/join")
    def join(body: InviteInput, who: User):
        with store.tx() as db:
            row = db.execute("SELECT id FROM groups WHERE invite_hash=?", (digest(body.code),)).fetchone()
            if not row:
                raise HTTPException(404, "Invalid invite code")
            size = db.execute("SELECT COUNT(*) FROM members WHERE group_id=?", (row["id"],)).fetchone()[0]
            if size >= 20:
                raise HTTPException(409, "Group is full (maximum 20 members)")
            db.execute("INSERT OR IGNORE INTO members VALUES(?,?,?)", (row["id"], who, "member"))
            store.emit(db, row["id"], who, "members_changed", {})
        return {"id": row["id"]}

    @app.post("/api/groups/{group}/invite")
    def rotate_invite(group: str, who: User):
        code = secrets.token_urlsafe(24)
        with store.tx() as db:
            store.member(db, group, who, True)
            db.execute("UPDATE groups SET invite_hash=? WHERE id=?", (digest(code), group))
        return {"invite_code": code}

    @app.get("/api/groups/{group}/members")
    def members(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return [dict(r) for r in db.execute("SELECT u.id,u.name,m.role FROM users u JOIN members m ON u.id=m.user_id WHERE m.group_id=?", (group,))]

    @app.put("/api/groups/{group}/settings")
    def change_settings(group: str, body: GroupSettings, who: User):
        with store.tx() as db:
            store.member(db, group, who, True)
            for member in body.twin_members:
                store.member(db, group, member)
            db.execute("UPDATE groups SET settings=? WHERE id=?", (packed(body.model_dump()), group))
            store.emit(db, group, who, "settings_changed", {})
        return body

    @app.get("/api/groups/{group}/inventory")
    def inventory(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return [{**i, "food": known(i["ingredient_id"]), "alert": freshness(i)} for i in store.items(db, "inventory", group) if i["grams"] > 0]

    @app.post("/api/groups/{group}/inventory", status_code=201)
    def add_inventory(group: str, body: InventoryInput, who: User):
        known(body.ingredient_id)
        with store.tx() as db:
            store.member(db, group, who, True)
            row = store.put(db, "inventory", group, who, body.model_dump(mode="json"))
            store.emit(db, group, who, "inventory_changed", {})
            return row

    @app.put("/api/groups/{group}/inventory/{key}")
    def edit_inventory(group: str, key: str, body: InventoryInput, who: User):
        known(body.ingredient_id)
        if body.version is None:
            raise HTTPException(422, "An inventory version is required to prevent lost updates")
        with store.tx() as db:
            store.member(db, group, who, True)
            old = store.get(db, key, "inventory")
            if old["group_id"] != group:
                raise HTTPException(403, "Inventory belongs to a different group")
            row = store.put(db, "inventory", group, old["owner_id"], body.model_dump(mode="json"), key, body.version)
            if old.get("estimated") and not body.estimated and old["ingredient_id"] == body.ingredient_id:
                remember_correction(store, db, group, who, body.ingredient_id, old["grams"], body.grams)
            store.put(db, "feedback", group, who, {"action": "note", "text": f"Inventory correction: {body.ingredient_id} {old['grams']}g -> {body.grams}g", "shared": False})
            store.emit(db, group, who, "inventory_changed", {})
            return row

    @app.delete("/api/groups/{group}/inventory/{key}")
    def discard_inventory(group: str, key: str, who: User, version: int = Query(ge=1)):
        with store.tx() as db:
            store.member(db, group, who, True)
            old = store.get(db, key, "inventory")
            if old["group_id"] != group:
                raise HTTPException(403, "Inventory belongs to a different group")
            old.update(grams=0, discarded=True)
            store.put(db, "inventory", group, old["owner_id"], old, key, version)
            store.emit(db, group, who, "inventory_changed", {})
        return {"ok": True}

    @app.post("/api/groups/{group}/consume")
    def consume_inventory(group: str, body: ConsumptionRequest, who: User):
        data = body.model_dump()
        with store.tx() as db:
            store.member(db, group, who)
            key, old = idempotent(store, db, "consumption", group, who, body.request_id, data)
            if old:
                return old
            consume(store, db, group, who, data["items"])
            return store.put(db, "consumption", group, who, {**data, "fingerprint": digest(packed(data))}, key)

    @app.get("/api/groups/{group}/prices")
    def prices(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return price_map(store, db, group)

    @app.post("/api/groups/{group}/prices")
    def add_price(group: str, body: PriceInput, who: User):
        known(body.ingredient_id)
        with store.tx() as db:
            store.member(db, group, who, True)
            return store.put(db, "price", group, who, {**body.model_dump(), "estimated": True})

    @app.post("/api/groups/{group}/receipts", status_code=201)
    def add_receipt(group: str, body: ReceiptConfirm, who: User):
        with store.tx() as db:
            store.member(db, group, who, True)
            return receipt(store, db, group, who, body.model_dump(mode="json"))

    @app.get("/api/groups/{group}/receipts")
    def receipts(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return store.items(db, "receipt", group)

    @app.get("/api/groups/{group}/reports")
    def reports(group: str, who: User, days: int = Query(default=7, ge=1, le=365), collective: bool = False):
        since = (date.today() - timedelta(days=days-1)).isoformat()
        with store.tx() as db:
            store.member(db, group, who)
            meals = [m for m in store.items(db, "meal", group) if m["eaten_on"] >= since and (collective or m["owner_id"] == who)]
            recs = [r for r in store.items(db, "receipt", group) if r["purchased_on"] >= since]
            config = json.loads(db.execute("SELECT settings FROM groups WHERE id=?", (group,)).fetchone()[0])
            count = db.execute("SELECT COUNT(*) FROM members WHERE group_id=?", (group,)).fetchone()[0]
        totals, categories = defaultdict(lambda: defaultdict(float)), defaultdict(int)
        alignment = []
        with store.tx() as db:
            for m in meals:
                raw_profile = db.execute("SELECT profile FROM users WHERE id=?", (m["owner_id"],)).fetchone()
                try:
                    target = target_for(json.loads(raw_profile[0]))
                except HTTPException:
                    continue
                matches = []
                for key in ("kcal", "protein", "carbs", "fat"):
                    value = m["nutrition"].get(key)
                    if value is None:
                        break
                    low, high = target[key + "_min"], target[key + "_max"]
                    matches.append(value / low if value < low and low else high / value if value > high else 1)
                if len(matches) == 4:
                    alignment.append(sum(matches) / 4 * 100)
        for m in meals:
            for k,v in m["nutrition"].items():
                if v is None:
                    totals[m["eaten_on"]][k] = None
                elif totals[m["eaten_on"]][k] is not None:
                    totals[m["eaten_on"]][k] += v
        for r in recs:
            for k,v in r["category_totals"].items():
                categories[k] += v
        spent = sum(r["paid_cents"] for r in recs)
        budget = config["budget_cents"] * (count if config["budget_mode"] == "per_person" else 1) * days/7
        return {"days": dict(sorted(totals.items())), "meal_count": len(meals), "paid_cents": spent,
                "category_cents": dict(categories), "per_person_cents": round(spent/count), "budget_cents": round(budget),
                "budget_note": "Weekly group budget prorated by the report length; dining attendance may differ.",
                "score": round(sum(alignment)/len(alignment)) if alignment else None,
                "score_note": "Recorded-meal target alignment (0–100), NOT a clinical health score or a full-day assessment. Average the four macro/calorie compliance ratios per recorded meal; missing targets produce no score.",
                "score_method": "target-alignment-v1", "scored_meals": len(alignment),
                "nutrition_is_estimate": True,
                "source": "; ".join(sorted({source for m in meals for source in m.get("sources", [])})) or "No recorded nutrition source yet",
                "disclaimer": DISCLAIMER}

    @app.post("/api/groups/{group}/meals", status_code=201)
    def meal(group: str, body: MealInput, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return record_meal(store, db, group, who, body.model_dump(mode="json"))

    @app.get("/api/groups/{group}/meals")
    def meals(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return store.items(db, "meal", group, who)

    @app.post("/api/groups/{group}/recognize")
    async def photo(group: str, who: User, kind: Annotated[Literal["inventory", "receipt", "meal"], Form()], image: Annotated[UploadFile, File()]):
        with store.tx() as db:
            store.member(db, group, who)
        raw = await image.read(6*1024*1024+1)
        await image.close()
        cleaned = clean_image(raw)
        result = await recognize(provider, kind, image=cleaned)
        with store.tx() as db:
            store.member(db, group, who)
            return store.put(db, "draft", group, who, calibrate(store, db, who, result))

    @app.post("/api/groups/{group}/drafts/text")
    async def text_draft(group: str, body: TextDraft, who: User):
        with store.tx() as db:
            store.member(db, group, who)
        result = await recognize(provider, body.kind, text=body.text)
        with store.tx() as db:
            return store.put(db, "draft", group, who, calibrate(store, db, who, result))

    @app.get("/api/drafts/{key}")
    def get_draft(key: str, who: User):
        with store.tx() as db:
            row = store.get(db, key, "draft")
            if row["owner_id"] != who:
                raise HTTPException(403, "Drafts are private")
            store.member(db, row["group_id"], who)
            return row

    @app.post("/api/drafts/{key}/refine")
    async def refine(key: str, body: TextInput, who: User):
        row = get_draft(key, who)
        if row["confirmed"]:
            raise HTTPException(409, "Confirmed drafts are immutable")
        result = await recognize(provider, row["kind"], text=body.text, previous=row)
        with store.tx() as db:
            return store.put(db, "draft", row["group_id"], who, calibrate(store, db, who, result), key, row["version"])

    @app.post("/api/drafts/{key}/confirm-inventory")
    def confirm_inventory(key: str, body: InventoryConfirmation, who: User):
        row = get_draft(key, who)
        with store.tx() as db:
            group = row["group_id"]
            store.member(db, group, who, True)
            confirm_draft(store, db, key, group, who, "inventory")
            results = []
            originals = list(row.get("items", []))
            for item in body.items:
                known(item.ingredient_id)
                original = next((x for x in originals if x.get("ingredient_id") == item.ingredient_id), None)
                if original:
                    originals.remove(original)
                    if original.get("estimated") and not item.estimated:
                        remember_correction(store, db, group, who, item.ingredient_id,
                                            original.get("uncalibrated_grams", original.get("grams")), item.grams)
                results.append(store.put(db, "inventory", group, who, item.model_dump(mode="json")))
            store.emit(db, group, who, "inventory_changed", {})
            return results

    @app.post("/api/groups/{group}/plans", status_code=202)
    def create_plan(group: str, body: PlanRequest, who: User):
        data = body.model_dump(mode="json")
        with store.tx() as db:
            store.member(db, group, who)
            key, existing = idempotent(store, db, "job", group, who, body.request_id, data)
            if existing:
                return public_job(existing)
            if isinstance(provider, DeepSeek) and not settings.api_key:
                raise HTTPException(503, "Configure DEEPSEEK_API_KEY; there is no fake AI mode")
            own_jobs = store.items(db, "job", owner=who)
            if sum(j["status"] in ("queued", "running") for j in own_jobs) >= 2:
                raise HTTPException(429, "At most two outstanding jobs are allowed per user")
            if sum(j["created_at"][:10] == date.today().isoformat() for j in own_jobs) >= 30:
                raise HTTPException(429, "Daily plan limit reached")
            context = snapshot(store, db, group, who, data)
            cache_context = json.loads(packed(context))
            cache_context["request"].pop("request_id", None)
            cache_key = digest(packed(cache_context))
            cached = next((j for j in own_jobs if j["group_id"] == group and j.get("cache_key") == cache_key
                           and j["status"] == "complete" and datetime.fromisoformat(j["updated_at"]) > datetime.now(timezone.utc)-timedelta(hours=6)), None)
            row = store.put(db, "job", group, who, {"status": "complete" if cached else "queued", "context": context,
                "result": cached.get("result") if cached else None, "cache_hit": bool(cached), "cache_key": cache_key,
                "fingerprint": digest(packed(data)), "message": "Reused validated result" if cached else "Queued"}, key)
            store.emit(db, key, who, "complete" if cached else "queued", {"job_id": key, "cache_hit": bool(cached)})
            return public_job(row)

    def public_job(row):
        return {k:v for k,v in row.items() if k not in ("context", "fingerprint", "cache_key")}

    @app.get("/api/groups/{group}/plans")
    def plans(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return [public_job(j) for j in store.items(db, "job", group, who)][:30]

    @app.get("/api/plans/{key}")
    def plan(key: str, who: User):
        with store.tx() as db:
            row = store.get(db, key, "job")
            if row["owner_id"] != who:
                raise HTTPException(403, "Only the request owner can access a planning job")
            store.member(db, row["group_id"], who)
            return public_job(row)

    @app.get("/api/plans/{key}/events")
    async def plan_events(key: str, request: Request, who: User, after: int = Query(default=0, ge=0), last_event_id: Annotated[str | None, Header()] = None):
        plan(key, who)
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))
        async def stream():
            cursor, ping = after, 0
            while not await request.is_disconnected():
                with store.tx() as db:
                    rows = store.events(db, key, cursor)
                    job = store.get(db, key, "job")
                for event in rows:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {packed(event['data'])}\n\n"
                if job["status"] in ("complete", "failed", "needs_input") and len(rows) < 100:
                    break
                ping += 1
                if ping % 20 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(.5)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/plans/{key}/select")
    def select_plan(key: str, body: Selection, who: User):
        row = plan(key, who)
        if row["status"] != "complete" or body.mode not in {v["mode"] for v in row["result"]["variants"]}:
            raise HTTPException(422, "Select a completed variant")
        with store.tx() as db:
            original = store.get(db, key, "job")
            live_context = snapshot(store, db, row["group_id"], who, original["context"]["request"])
            # Preference feedback can legitimately evolve after generation; safety inputs cannot.
            safety_keys = ("request", "diners", "inventory", "foods", "prices")
            if any(packed(live_context[k]) != packed(original["context"][k]) for k in safety_keys):
                raise HTTPException(409, "Profiles, inventory or prices changed. Generate a fresh plan before selection.")
            store.put(db, "feedback", row["group_id"], who, {"action": "select", "mode": body.mode, "job_id": key, "shared": True, "text": ""})
            group_plan = store.put(db, "selected_plan", row["group_id"], who,
                {"job_id": key, "mode": body.mode, "plan": next(v for v in row["result"]["variants"] if v["mode"] == body.mode)})
            store.emit(db, row["group_id"], who, "plans_changed", {})
            return group_plan

    @app.get("/api/groups/{group}/selected-plans")
    def selected_plans(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return store.items(db, "selected_plan", group)[:10]

    @app.post("/api/groups/{group}/feedback")
    def feedback(group: str, body: Feedback, who: User):
        if body.job_id:
            job = plan(body.job_id, who)
            if job["group_id"] != group:
                raise HTTPException(403, "Plan belongs to another group")
        with store.tx() as db:
            store.member(db, group, who)
            return store.put(db, "feedback", group, who, body.model_dump())

    @app.get("/api/groups/{group}/feedback")
    def own_feedback(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            return store.items(db, "feedback", group, who)

    @app.delete("/api/feedback/{key}")
    def delete_feedback(key: str, who: User):
        with store.tx() as db:
            row = store.get(db, key, "feedback")
            if row["owner_id"] != who:
                raise HTTPException(403, "Only your own feedback can be removed")
            db.execute("DELETE FROM entities WHERE id=?", (key,))
            # Invalidate derived memory immediately when consent/data is withdrawn.
            db.execute("DELETE FROM entities WHERE kind='twin' AND (scope=? OR scope=?)", (who, row["group_id"]))
        return {"ok": True}

    @app.get("/api/twins/personal")
    def personal_twin(who: User):
        with store.tx() as db:
            return build_twin(store, db, "", who)

    @app.get("/api/groups/{group}/twin")
    def group_twin(group: str, who: User):
        with store.tx() as db:
            store.member(db, group, who)
            row = db.execute("SELECT owner,settings FROM groups WHERE id=?", (group,)).fetchone()
            config = json.loads(row["settings"])
            allowed = row["owner"] == who or config["twin_visibility"] == "all" or (config["twin_visibility"] == "selected" and who in config["twin_members"])
            if not allowed:
                raise HTTPException(403, "The group twin is not visible to you")
            return build_twin(store, db, group, who, collective=True)

    @app.get("/api/notifications")
    def notifications(who: User):
        with store.tx() as db:
            return store.items(db, "notification", owner=who)[:60]

    @app.post("/api/notifications/{key}/read")
    def read_notification(key: str, who: User):
        with store.tx() as db:
            row = store.get(db, key, "notification")
            if row["owner_id"] != who:
                raise HTTPException(403, "Notification is private")
            row["read"] = True
            return store.put(db, "notification", row["group_id"], who, row, key)

    @app.websocket("/api/groups/{group}/live")
    async def live(ws: WebSocket, group: str):
        await ws.accept()
        try:
            message = await asyncio.wait_for(ws.receive_json(), timeout=5)
            token = message.get("token", "")
            who = authenticate(token)
            with store.tx() as db:
                store.member(db, group, who)
                cursor = db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE scope=?", (group,)).fetchone()[0]
            await ws.send_json({"type": "ready"})
            while True:
                authenticate(token)
                with store.tx() as db:
                    store.member(db, group, who)
                    events = store.events(db, group, cursor)
                for event in events:
                    cursor = event["id"]
                    await ws.send_json(event)
                # Read/ping cycle detects disconnects; only invalidation events are shared.
                try:
                    await asyncio.wait_for(ws.receive_text(), timeout=2)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping"})
        except (HTTPException, asyncio.TimeoutError, ValueError, KeyError, TypeError):
            with contextlib.suppress(Exception):
                await ws.close(code=4401)
        except (WebSocketDisconnect, RuntimeError):
            pass

    web = ROOT / "web"
    if web.exists():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
    return app


app = create_app()
