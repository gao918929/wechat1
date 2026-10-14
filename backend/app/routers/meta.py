"""Knowledge-base lookups for the UI, app metadata, health check and the WebSocket endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..auth import current_user, read_token
from ..config import settings
from ..db import SessionLocal
from ..models import Membership, User
from ..realtime import hub
from ..services.nutrition import DISCLAIMER
from ..wiki import SECTION_LABELS, get_wiki

router = APIRouter(tags=["meta"])

GOALS = [{"key": "fat_loss", "label": "减脂"}, {"key": "muscle_gain", "label": "增肌"},
         {"key": "maintain", "label": "保持"}, {"key": "stomach", "label": "养胃"}]
AVOID_OPTIONS = [{"key": k, "label": v} for k, v in [
    ("spicy", "辣"), ("seafood", "海鲜"), ("fatty_meat", "肥肉"), ("cilantro", "香菜"), ("pork", "猪肉"),
    ("beef", "牛肉"), ("lamb", "羊肉"), ("fish", "鱼"), ("organ", "内脏"), ("high_sugar", "甜食")]]
ALLERGEN_OPTIONS = [{"key": k, "label": v} for k, v in [
    ("peanut", "花生"), ("seafood", "海鲜"), ("shellfish", "虾蟹贝"), ("fish", "鱼"), ("egg", "鸡蛋"), ("milk", "牛奶"),
    ("soy", "大豆"), ("wheat", "小麦/麸质"), ("sesame", "芝麻"), ("nut", "坚果"), ("mango", "芒果")]]


@router.get("/api/health")
def health():
    wiki = get_wiki()
    return {"status": "ok", "llm_online": settings.llm_online, "model": settings.deepseek_model,
            "vision_model": settings.vision_model, "wechat": settings.wechat_enabled,
            "wiki": {"ingredients": len(wiki.ingredients), "dishes": len(wiki.dishes), "diet_models": len(wiki.diet_models)}}


@router.get("/api/meta")
def meta():
    wiki = get_wiki()
    return {
        "goals": GOALS, "avoid_options": AVOID_OPTIONS, "allergen_options": ALLERGEN_OPTIONS,
        "dietary_groups": [{"key": m.id, "label": m.name, "special_need": m.flag("special_need")}
                           for m in wiki.diet_models.values()],
        "activity_levels": [{"key": "sedentary", "label": "久坐"}, {"key": "light", "label": "轻体力"},
                            {"key": "moderate", "label": "中体力"}, {"key": "active", "label": "重体力"}],
        "reference_objects": [{"key": r.key, "name": r.name, "size_cm": r.size_cm} for r in wiki.reference_objects.values()],
        "sections": SECTION_LABELS, "disclaimer": DISCLAIMER, "llm_online": settings.llm_online,
    }


@router.get("/api/wiki/ingredients")
def search_ingredients(q: str = "", limit: int = 20, _: User = Depends(current_user)):
    wiki = get_wiki()
    q = q.strip()
    rows = [i for i in wiki.ingredients.values()
            if not q or q in i.name or q.lower() in i.en.lower() or any(q in a for a in i.aliases)]
    return [i.brief() for i in rows[:max(1, min(limit, 100))]]


@router.get("/api/wiki/dishes")
def list_dishes(kind: str = "", _: User = Depends(current_user)):
    wiki = get_wiki()
    return [d.to_dict() for d in wiki.dishes.values() if not kind or d.kind == kind]


@router.get("/api/wiki/sources")
def sources():
    return {"sources": get_wiki().sources_text()}


@router.websocket("/ws/groups/{gid}")
async def group_socket(ws: WebSocket, gid: int, token: str = ""):
    uid = read_token(token) if token else None
    if uid is None:
        await ws.close(code=4401)
        return
    db = SessionLocal()
    try:
        ok = db.scalar(select(Membership).where(Membership.group_id == gid, Membership.user_id == uid)) is not None
    finally:
        db.close()
    if not ok:
        await ws.close(code=4403)
        return
    await ws.accept()
    await hub.join(gid, ws)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(gid, ws)
