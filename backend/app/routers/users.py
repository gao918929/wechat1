"""Login, profile, personal twin, nutrition and notifications."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, make_token
from ..db import get_db
from ..models import Group, MealRecord, Membership, Notification, User
from ..services import twin as twin_service
from ..services.nl import normalize_avoid
from ..services.nutrition import DISCLAIMER, add_nutrition, daily_targets, health_score
from ..services.planning import user_profile
from ..wechat import code2session
from ..wiki import get_wiki

router = APIRouter(prefix="/api", tags=["users"])


class LoginIn(BaseModel):
    code: str = ""
    dev_id: str = ""
    nickname: str = ""


def group_brief(g: Group, user_id: int) -> dict:
    role = next((m.role for m in g.memberships if m.user_id == user_id), None)
    return {"id": g.id, "name": g.name, "kind": g.kind, "role": role, "invite_code": g.invite_code,
            "members": len(g.memberships), "budget_mode": g.budget_mode, "budget_amount": g.budget_amount,
            "twin_visibility": g.twin_visibility, "owner_id": g.owner_id}


def user_out(u: User) -> dict:
    return {"id": u.id, "nickname": u.nickname, "sex": u.sex, "age": u.age, "height_cm": u.height_cm,
            "weight_kg": u.weight_kg, "body_fat_pct": u.body_fat_pct, "activity_level": u.activity_level,
            "goal": u.goal, "dietary_groups": u.dietary_groups, "allergens": u.allergens,
            "avoidances": u.avoidances, "likes": u.likes, "max_spicy": u.max_spicy, "city": u.city}


@router.post("/auth/login")
async def login(body: LoginIn, db: Session = Depends(get_db)):
    if not body.code and not body.dev_id:
        raise HTTPException(400, "缺少 code")
    try:
        openid = await code2session(body.code, body.dev_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid, nickname=body.nickname or "我")
        db.add(user)
        db.flush()
        kitchen = Group(name="我的厨房", kind="personal", owner_id=user.id)
        db.add(kitchen)
        db.flush()
        db.add(Membership(group_id=kitchen.id, user_id=user.id, role="admin"))
        db.commit()
        db.refresh(user)
    elif body.nickname and not user.nickname:
        user.nickname = body.nickname
        db.commit()
    groups = [group_brief(m.group, user.id) for m in user.memberships]
    return {"token": make_token(user.id), "user": user_out(user), "groups": groups}


class ProfileIn(BaseModel):
    nickname: str | None = None
    sex: str | None = Field(None, pattern="^(male|female|)$")
    age: int | None = Field(None, ge=1, le=120)
    height_cm: float | None = Field(None, gt=50, lt=250)
    weight_kg: float | None = Field(None, gt=10, lt=300)
    body_fat_pct: float | None = Field(None, ge=2, le=70)
    activity_level: str | None = Field(None, pattern="^(sedentary|light|moderate|active)$")
    goal: str | None = Field(None, pattern="^(fat_loss|muscle_gain|maintain|stomach)$")
    dietary_groups: list[str] | None = None
    allergens: list[str] | None = None
    avoidances: list[str] | None = None
    likes: list[str] | None = None
    max_spicy: int | None = Field(None, ge=0, le=3)
    city: str | None = None


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": user_out(user), "groups": [group_brief(m.group, user.id) for m in user.memberships]}


@router.put("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wiki = get_wiki()
    data = body.model_dump(exclude_none=True)
    if "dietary_groups" in data:
        data["dietary_groups"] = [g for g in data["dietary_groups"] if g in wiki.diet_models]
    for key in ("allergens", "avoidances", "likes"):
        if key in data:  # free text ("辣"、"洋葱") → constraint labels / canonical ingredient names
            data[key] = list(dict.fromkeys(normalize_avoid(v, wiki) or v.strip() for v in data[key] if v.strip()))
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return {"user": user_out(user)}


@router.get("/me/targets")
def my_targets(user: User = Depends(current_user)):
    wiki = get_wiki()
    daily = daily_targets(user_profile(user), wiki)
    meals = {m: {"kcal": round(daily["kcal"] * s), "protein_g": round(daily["protein_g"] * s)} for m, s in wiki.meal_shares.items()}
    return {"daily": daily, "meals": meals, "disclaimer": DISCLAIMER}


def nutrition_report(records: list[MealRecord], daily: dict, days: int) -> dict:
    by_day: dict[str, dict] = {}
    for r in records:
        key = r.eaten_on.isoformat()
        by_day[key] = add_nutrition(by_day.get(key, {}), r.nutrition or {})
    series = []
    for i in range(days - 1, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        n = by_day.get(d, {})
        s = health_score(n, daily) if n else None
        series.append({"date": d, "kcal": round(n.get("kcal", 0)), "protein": round(n.get("protein", 0), 1),
                       "fat": round(n.get("fat", 0), 1), "carb": round(n.get("carb", 0), 1),
                       "vc": round(n.get("vc", 0)), "ca": round(n.get("ca", 0)), "fe": round(n.get("fe", 0), 1),
                       "salt_g": round(n.get("salt_g", 0), 1), "vegetable_g": round(n.get("vegetable_g", 0)),
                       "score": s["score"] if s else None, "reasons": s["reasons"] if s else []})
    logged = [x for x in series if x["kcal"]]
    avg = {k: round(sum(x[k] for x in logged) / len(logged), 1) for k in ("kcal", "protein", "fat", "carb")} if logged else {}
    return {"series": series, "average": avg, "target": {k: daily[k] for k in ("kcal", "protein_g", "fat_g", "carb_g")},
            "score": round(sum(x["score"] for x in logged) / len(logged)) if logged else None,
            "logged_days": len(logged), "disclaimer": DISCLAIMER,
            "sources": "《中国食物成分表》第6版；《中国居民膳食营养素参考摄入量（2023版）》"}


@router.get("/me/nutrition")
def my_nutrition(days: int = 7, user: User = Depends(current_user), db: Session = Depends(get_db)):
    days = max(1, min(days, 31))
    since = date.today() - timedelta(days=days - 1)
    records = db.scalars(select(MealRecord).where(MealRecord.user_id == user.id, MealRecord.eaten_on >= since)).all()
    return nutrition_report(list(records), daily_targets(user_profile(user), get_wiki()), days)


@router.get("/me/meals")
def my_meals(days: int = 7, user: User = Depends(current_user), db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=max(1, min(days, 31)) - 1)
    rows = db.scalars(select(MealRecord).where(MealRecord.user_id == user.id, MealRecord.eaten_on >= since)
                      .order_by(MealRecord.eaten_on.desc(), MealRecord.id.desc())).all()
    return [{"id": r.id, "date": r.eaten_on.isoformat(), "meal": r.meal, "context": r.context, "dishes": r.dishes,
             "kcal": round((r.nutrition or {}).get("kcal", 0)), "plan_id": r.plan_id} for r in rows]


# ---------------------------------------------------------------- personal twin (owner only)
class TwinEdit(BaseModel):
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    notes: str | None = None
    remove_dish_scores: list[str] | None = None


@router.get("/me/twin")
def my_twin(user: User = Depends(current_user), db: Session = Depends(get_db)):
    twin = twin_service.get_twin(db, "user", user.id)
    db.commit()
    return {"version": twin.version, "updated_at": twin.updated_at.isoformat(), "data": twin.data,
            "visibility": "仅本人可见、可编辑"}


@router.put("/me/twin")
def edit_my_twin(body: TwinEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wiki = get_wiki()
    twin = twin_service.get_twin(db, "user", user.id)
    data = dict(twin.data or {})
    manual = dict(data.get("manual") or {})
    if body.likes is not None:
        manual["likes"] = [wiki.resolve(x) or x for x in body.likes]
    if body.dislikes is not None:
        manual["dislikes"] = [wiki.resolve(x) or x for x in body.dislikes]
    if body.notes is not None:
        manual["notes"] = body.notes
    data["manual"] = manual
    twin.data = data
    db.flush()
    for dish in body.remove_dish_scores or []:
        twin_service.record(db, user.id, None, "rating", {"dish": dish, "score": 3})
    twin = twin_service.refresh_user_twin(db, user, wiki)
    db.commit()
    return {"version": twin.version, "data": twin.data}


@router.post("/me/twin/refresh")
def refresh_my_twin(user: User = Depends(current_user), db: Session = Depends(get_db)):
    wiki = get_wiki()
    twin = twin_service.refresh_user_twin(db, user, wiki)
    for m in user.memberships:
        twin_service.refresh_group_twin(db, m.group, wiki)
    db.commit()
    return {"version": twin.version, "data": twin.data}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.id.desc()).limit(50)).all()
    return {"unread": sum(1 for r in rows if not r.read),
            "items": [{"id": r.id, "title": r.title, "body": r.body, "link": r.link, "read": r.read,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "通知不存在")
    n.read = True
    db.commit()
    return {"ok": True}
