"""Households / dormitories: membership, roles, pooled budget, group twin and group nutrition."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, membership, require_group
from ..db import get_db
from ..models import Group, MealRecord, Membership, User
from ..realtime import hub
from ..services import twin as twin_service
from ..services.nutrition import DISCLAIMER, add_nutrition, daily_targets
from ..services.planning import user_profile
from ..wiki import get_wiki
from .users import group_brief

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    kind: str = Field("dorm", pattern="^(dorm|household)$")


class JoinIn(BaseModel):
    invite_code: str


class GroupUpdate(BaseModel):
    name: str | None = None
    budget_mode: str | None = Field(None, pattern="^(per_person|total)$")
    budget_amount: float | None = Field(None, ge=0)
    twin_visibility: str | None = Field(None, pattern="^(owner|selected|all)$")
    twin_visible_member_ids: list[int] | None = None


class RoleIn(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


def group_detail(g: Group, user_id: int) -> dict:
    out = group_brief(g, user_id)
    out["member_list"] = [{"id": m.user_id, "nickname": m.user.nickname or f"成员{m.user_id}", "role": m.role,
                           "avoidances": m.user.avoidances, "allergens": m.user.allergens}
                          for m in sorted(g.memberships, key=lambda m: m.id)]
    out["twin_visible_member_ids"] = g.twin_visible_member_ids
    return out


@router.get("")
def list_groups(user: User = Depends(current_user)):
    return [group_brief(m.group, user.id) for m in user.memberships]


@router.post("")
def create_group(body: GroupIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = Group(name=body.name, kind=body.kind, owner_id=user.id)
    db.add(g)
    db.flush()
    db.add(Membership(group_id=g.id, user_id=user.id, role="admin"))
    db.commit()
    db.refresh(g)
    return group_detail(g, user.id)


@router.post("/join")
def join_group(body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.scalar(select(Group).where(Group.invite_code == body.invite_code.strip().upper()))
    if g is None:
        raise HTTPException(404, "邀请码无效")
    if not any(m.user_id == user.id for m in g.memberships):
        db.add(Membership(group_id=g.id, user_id=user.id, role="member"))
        db.commit()
        db.refresh(g)
        hub.publish(g.id, "member.joined", user_id=user.id, nickname=user.nickname)
    return group_detail(g, user.id)


@router.get("/{gid}")
def get_group(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return group_detail(require_group(db, gid, user), user.id)


@router.put("/{gid}")
def update_group(gid: int, body: GroupUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = require_group(db, gid, user, admin=True)
    data = body.model_dump(exclude_none=True)
    if ("twin_visibility" in data or "twin_visible_member_ids" in data) and g.owner_id != user.id:
        raise HTTPException(403, "只有创建者可以设置群体孪生的可见范围")
    for k, v in data.items():
        setattr(g, k, v)
    db.commit()
    hub.publish(gid, "group.updated", fields=list(data))
    return group_detail(g, user.id)


@router.put("/{gid}/members/{uid}")
def set_role(gid: int, uid: int, body: RoleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = require_group(db, gid, user, admin=True)
    m = db.scalar(select(Membership).where(Membership.group_id == gid, Membership.user_id == uid))
    if m is None:
        raise HTTPException(404, "成员不存在")
    if uid == g.owner_id and body.role != "admin":
        raise HTTPException(400, "创建者必须是管理员")
    m.role = body.role
    db.commit()
    hub.publish(gid, "member.role", user_id=uid, role=body.role)
    return group_detail(g, user.id)


@router.delete("/{gid}/members/{uid}")
def remove_member(gid: int, uid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.get(Group, gid)
    if g is None:
        raise HTTPException(404, "小组不存在")
    if uid != user.id:
        require_group(db, gid, user, admin=True)
    else:
        membership(db, gid, user)
    if uid == g.owner_id:
        raise HTTPException(400, "创建者不能退出，可先转移管理员")
    m = db.scalar(select(Membership).where(Membership.group_id == gid, Membership.user_id == uid))
    if m:
        db.delete(m)
        db.commit()
    hub.publish(gid, "member.left", user_id=uid)
    return {"ok": True}


@router.get("/{gid}/twin")
def group_twin(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = require_group(db, gid, user)
    if not twin_service.can_view_group_twin(g, user.id):
        raise HTTPException(403, "群体孪生的可见范围不包含你")
    twin = twin_service.get_twin(db, "group", gid)
    db.commit()
    return {"version": twin.version, "updated_at": twin.updated_at.isoformat(), "data": twin.data,
            "visibility": g.twin_visibility,
            "note": "成员可在“我的数字孪生”中调整自己贡献的偏好数据"}


@router.get("/{gid}/nutrition")
def group_nutrition(gid: int, days: int = 7, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = require_group(db, gid, user)
    wiki = get_wiki()
    days = max(1, min(days, 31))
    since = date.today() - timedelta(days=days - 1)
    out = []
    for m in g.memberships:
        recs = db.scalars(select(MealRecord).where(MealRecord.user_id == m.user_id, MealRecord.group_id == gid,
                                                   MealRecord.eaten_on >= since)).all()
        total: dict = {}
        for r in recs:
            total = add_nutrition(total, r.nutrition or {})
        daily = daily_targets(user_profile(m.user), wiki)
        out.append({"user_id": m.user_id, "nickname": m.user.nickname or f"成员{m.user_id}", "meals": len(recs),
                    "avg_kcal": round(total.get("kcal", 0) / days), "avg_protein": round(total.get("protein", 0) / days, 1),
                    "target_kcal": daily["kcal"], "target_protein": daily["protein_g"]})
    return {"days": days, "members": out, "disclaimer": DISCLAIMER}
