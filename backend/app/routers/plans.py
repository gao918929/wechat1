"""Meal plans: create (background job), stream progress (SSE), choose / edit / rate, mark eaten, shopping list."""
from __future__ import annotations

import copy
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import dishes as D
from ..auth import current_user, membership, require_group
from ..db import get_db
from ..jobs import jobs
from ..models import MealPlan, MealRecord, User
from ..realtime import hub
from ..services import inventory as inv
from ..services import twin as twin_service
from ..services.pricing import price_history
from ..services.shopping import build_shopping, shopping_text
from ..wiki import get_wiki

router = APIRouter(prefix="/api", tags=["plans"])


class PlanIn(BaseModel):
    instruction: str = Field("", max_length=1000)
    days: int | None = Field(None, ge=1, le=14)
    meals: list[str] | None = None
    people: int | None = Field(None, ge=1, le=20)
    diner_ids: list[int] | None = None
    overrides: list[str] = Field(default_factory=list)  # soft constraints the user chose to override
    alternatives: str = Field("auto", pattern="^(auto|always|never)$")
    start_date: date | None = None
    cache: bool = True
    refresh_twin: bool = False


def plan_out(p: MealPlan, since: int | None = None, full: bool = True) -> dict:
    out = {"id": p.id, "group_id": p.group_id, "status": p.status, "instruction": p.instruction, "options": p.options,
           "chosen_variant": p.chosen_variant, "created_at": p.created_at.isoformat(),
           "finished_at": p.finished_at.isoformat() if p.finished_at else None, "error": p.error}
    if since is not None:
        out["events"] = [e for e in (p.events or []) if e["seq"] >= since]
    if full and p.status == "done":
        out["result"] = p.result
    elif p.status == "done":
        top = next((v for v in p.result.get("variants", []) if v["key"] == (p.chosen_variant or p.result.get("recommended"))), None)
        if top:
            out["summary"] = {"title": top["title"], **top["summary"]}
            out["days"], out["meals"] = p.result.get("days"), p.result.get("meals")
    return out


def _plan(db: Session, pid: int, user: User) -> MealPlan:
    p = db.get(MealPlan, pid)
    if p is None:
        raise HTTPException(404, "计划不存在")
    membership(db, p.group_id, user)
    return p


@router.post("/groups/{gid}/plans")
async def create_plan(gid: int, body: PlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    options = body.model_dump(exclude={"instruction"}, exclude_none=True)
    if body.start_date:
        options["start_date"] = body.start_date.isoformat()
    if options.get("meals"):
        options["meals"] = [m for m in options["meals"] if m in ("breakfast", "lunch", "dinner")] or None
    plan = MealPlan(group_id=gid, created_by=user.id, instruction=body.instruction, options=options, status="pending")
    db.add(plan)
    db.commit()
    jobs.start(plan.id)  # runs server-side even if the client disconnects
    return {"id": plan.id, "status": plan.status, "stream": f"/api/plans/{plan.id}/stream"}


@router.get("/groups/{gid}/plans")
def list_plans(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    rows = db.scalars(select(MealPlan).where(MealPlan.group_id == gid).order_by(MealPlan.id.desc()).limit(30)).all()
    return [plan_out(p, full=False) for p in rows]


@router.get("/plans/{pid}")
def get_plan(pid: int, since: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return plan_out(_plan(db, pid, user), since=since)


@router.get("/plans/{pid}/stream")
async def stream_plan(pid: int, since: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _plan(db, pid, user)

    async def gen():
        yield "retry: 3000\n\n"
        async for ev in jobs.stream(pid, since):
            if ev["type"] == "ping":
                yield ": ping\n\n"
                continue
            yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _variant(p: MealPlan, key: str | None) -> dict:
    if p.status != "done":
        raise HTTPException(409, "计划尚未生成完成")
    key = key or p.chosen_variant or p.result["recommended"]
    v = next((v for v in p.result["variants"] if v["key"] == key), None)
    if v is None:
        raise HTTPException(404, "方案不存在")
    return v


class ChooseIn(BaseModel):
    variant: str = Field(pattern="^(balanced|health|budget)$")


@router.post("/plans/{pid}/choose")
def choose_variant(pid: int, body: ChooseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _plan(db, pid, user)
    _variant(p, body.variant)
    p.chosen_variant = body.variant
    twin_service.record(db, user.id, p.group_id, "choose_variant", {"variant": body.variant, "plan_id": p.id})
    db.commit()
    hub.publish(p.group_id, "plan.chosen", plan_id=p.id, variant=body.variant, by=user.nickname)
    return {"ok": True, "chosen_variant": p.chosen_variant}


def _recompute(db: Session, p: MealPlan, v: dict) -> None:
    """Re-derive cost + shopping list after a dish edit (current inventory, price memory)."""
    wiki = get_wiki()
    need: dict[str, float] = {}
    for d in v["days"]:
        for m in d["meals"]:
            m["cost"] = 0.0
            for x in m["dishes"]:
                for ing in x["ingredients"]:
                    need[ing["name"]] = need.get(ing["name"], 0) + ing["grams"] * x["servings"]
                m["cost"] = round(m["cost"] + x.get("cost", 0), 2)
    shop = build_shopping(need, inv.snapshot(db, p.group_id, wiki), price_history(db, p.group_id, wiki), wiki,
                          people=len(p.result.get("diners", [])) or 1, budget_total=(p.result.get("budget") or {}).get("total"))
    v["shopping"] = shop
    s = v["summary"]
    s.update(total_cost=shop["total_cost"], per_person_cost=shop["per_person_cost"],
             within_budget=None if not s.get("budget_total") else shop["total_cost"] <= s["budget_total"],
             budget_utilization=round(shop["total_cost"] / s["budget_total"], 2) if s.get("budget_total") else None)
    v.setdefault("edited", True)


class FeedbackIn(BaseModel):
    kind: str = Field(pattern="^(rate|favorite|unfavorite|delete_dish|replace_dish|substitute)$")
    variant: str | None = None
    day: int | None = None
    meal: str | None = None
    dish: str | None = None
    score: int | None = Field(None, ge=1, le=5)
    with_dish: str | None = None
    from_ingredient: str | None = None
    to_ingredient: str | None = None


@router.post("/plans/{pid}/feedback")
def plan_feedback(pid: int, body: FeedbackIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Explicit feedback; every edit is also written to the digital twin as a learning signal."""
    p = _plan(db, pid, user)
    result = copy.deepcopy(p.result)
    v = next((x for x in result.get("variants", []) if x["key"] == (body.variant or p.chosen_variant or result.get("recommended"))), None)
    if v is None:
        raise HTTPException(409, "计划尚未生成完成")
    wiki = get_wiki()

    def locate() -> tuple[dict, dict]:
        d = next((d for d in v["days"] if d["day"] == body.day), None)
        m = next((m for m in (d or {}).get("meals", []) if m["meal"] == body.meal), None)
        x = next((x for x in (m or {}).get("dishes", []) if x["name"] == body.dish), None)
        if x is None:
            raise HTTPException(404, "找不到这道菜")
        return m, x

    message = ""
    if body.kind == "rate":
        if body.score is None:
            raise HTTPException(400, "缺少评分")
        dishes = [body.dish] if body.dish else list(dict.fromkeys(x["name"] for d in v["days"] for m in d["meals"] for x in m["dishes"]))
        twin_service.record(db, user.id, p.group_id, "rating", {"dishes": dishes, "score": body.score, "plan_id": p.id})
        message = "感谢评分，下周方案会参考"
    elif body.kind in ("favorite", "unfavorite"):
        if not body.dish:
            raise HTTPException(400, "缺少菜名")
        twin_service.record(db, user.id, p.group_id, body.kind, {"dish": body.dish})
        message = "已收藏" if body.kind == "favorite" else "已取消收藏"
    elif body.kind == "delete_dish":
        m, x = locate()
        if len(m["dishes"]) <= 1:
            raise HTTPException(400, "每餐至少保留一道菜")
        m["dishes"].remove(x)
        twin_service.record(db, user.id, p.group_id, "delete", {"dish": x["name"]})
        _recompute(db, p, v)
        message = f"已删除 {x['name']}，购物清单已更新"
    elif body.kind == "replace_dish":
        m, x = locate()
        t = wiki.dishes.get(body.with_dish or "")
        if t is None:
            raise HTTPException(400, "替换菜品不在菜谱库中")
        new = D.from_template(t)
        hard = D.matches(new, set(result.get("hard_constraint_labels") or []), wiki)
        if hard:
            raise HTTPException(400, "替换菜含有硬约束禁忌，不能替换")
        n = D.per_serving_nutrition(new, wiki)
        c = D.per_serving_cost(new, wiki, price_history(db, p.group_id, wiki))
        x.update(name=new["name"], en=new["en"], kind=new["kind"], spicy=new["spicy"], minutes=new["minutes"],
                 steps=new["steps"], source=new["source"], ingredients=new["ingredients"],
                 nutrition_per_serving={k: n[k] for k in ("kcal", "protein", "fat", "carb")},
                 cost_per_serving=c["cost"], cost_estimated=c["estimated"], cost=round(c["cost"] * x["servings"], 2))
        twin_service.record(db, user.id, p.group_id, "substitute", {"from_dish": body.dish, "to_dish": new["name"]})
        _recompute(db, p, v)
        message = f"已将 {body.dish} 替换为 {new['name']}"
    elif body.kind == "substitute":
        m, x = locate()
        new = D.substitute(x, body.from_ingredient or "", body.to_ingredient or "", wiki)
        if new is None:
            raise HTTPException(400, "这道菜不含该食材")
        n = D.per_serving_nutrition(new, wiki)
        c = D.per_serving_cost(new, wiki, price_history(db, p.group_id, wiki))
        x.update(name=new["name"], ingredients=new["ingredients"], notes=new.get("notes", []),
                 nutrition_per_serving={k: n[k] for k in ("kcal", "protein", "fat", "carb")},
                 cost_per_serving=c["cost"], cost=round(c["cost"] * x["servings"], 2))
        twin_service.record(db, user.id, p.group_id, "substitute", {"from": body.from_ingredient, "to": body.to_ingredient})
        _recompute(db, p, v)
        message = f"已将 {body.from_ingredient} 换成 {body.to_ingredient}"
    p.result = result
    db.commit()
    if body.kind in ("delete_dish", "replace_dish", "substitute"):
        hub.publish(p.group_id, "plan.edited", plan_id=p.id, by=user.nickname)
    return {"ok": True, "message": message, "variant": v if body.kind in ("delete_dish", "replace_dish", "substitute") else None}


class EatIn(BaseModel):
    variant: str | None = None
    day: int
    meal: str = Field(pattern="^(breakfast|lunch|dinner)$")
    deduct_inventory: bool = True


@router.post("/plans/{pid}/eat")
def mark_eaten(pid: int, body: EatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Manual deduction path: mark a planned meal as cooked & eaten."""
    p = _plan(db, pid, user)
    v = _variant(p, body.variant)
    d = next((d for d in v["days"] if d["day"] == body.day), None)
    m = next((m for m in (d or {}).get("meals", []) if m["meal"] == body.meal), None)
    if m is None:
        raise HTTPException(404, "找不到该餐")
    wiki = get_wiki()
    key = f"{v['key']}:{body.day}:{body.meal}"
    state = dict(p.shopping_state or {})
    cooked = list(state.get("cooked", []))
    changes = []
    if body.deduct_inventory and key not in cooked:  # the shared meal is deducted once for the whole group
        for x in m["dishes"]:
            for ing in x["ingredients"]:
                changes += inv.deduct(db, p.group_id, ing["name"], wiki, grams=ing["grams"] * x["servings"])
        cooked.append(key)
        state["cooked"] = cooked
        p.shopping_state = state
        hub.publish(p.group_id, "inventory.updated", by=user.nickname, action="meal")
    mine = m["diners"].get(f"u{user.id}") or next(iter(m["diners"].values()))
    eaten = [x["name"] for x in m["dishes"] if not x.get("suitable_for") or (user.nickname or "") in x.get("suitable_for", [])
             or len(x.get("suitable_for", [])) == len(m["diners"])]
    db.add(MealRecord(user_id=user.id, group_id=p.group_id, eaten_on=date.fromisoformat(d["date"]), meal=body.meal,
                      context="home", dishes=eaten, nutrition=mine["intake"], plan_id=p.id))
    twin_service.record(db, user.id, p.group_id, "meal", {"dishes": eaten, "context": "home"})
    db.commit()
    return {"ok": True, "inventory_changes": changes, "nutrition": mine["intake"], "already_deducted": not changes and key in cooked}


@router.get("/plans/{pid}/shopping")
def get_shopping(pid: int, variant: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _plan(db, pid, user)
    v = _variant(p, variant)
    checked = (p.shopping_state or {}).get(v["key"], {})
    return {"variant": v["key"], "title": v["title"], "shopping": v["shopping"], "checked": checked,
            "start_date": p.result["start_date"], "days": p.result["days"]}


class CheckIn(BaseModel):
    variant: str | None = None
    name: str
    checked: bool


@router.post("/plans/{pid}/shopping/check")
def check_item(pid: int, body: CheckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _plan(db, pid, user)
    v = _variant(p, body.variant)
    state = copy.deepcopy(p.shopping_state or {})
    state.setdefault(v["key"], {})[body.name] = body.checked
    p.shopping_state = state
    db.commit()
    hub.publish(p.group_id, "shopping.checked", plan_id=p.id, variant=v["key"], name=body.name, checked=body.checked,
                by=user.nickname)
    return {"ok": True, "checked": state[v["key"]]}


@router.get("/plans/{pid}/shopping/text", response_class=PlainTextResponse)
def shopping_as_text(pid: int, variant: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _plan(db, pid, user)
    v = _variant(p, variant)
    title = f"{p.result['start_date']} 起 {p.result['days']} 天 · {v['title']}"
    return shopping_text(v["shopping"], title, (p.shopping_state or {}).get(v["key"], {}))
