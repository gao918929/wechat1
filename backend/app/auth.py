"""Signed bearer tokens and request dependencies (current user, group membership/roles)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Group, Membership, User

TOKEN_TTL = 30 * 24 * 3600


def make_token(user_id: int) -> str:
    body = f"{user_id}.{int(time.time()) + TOKEN_TTL}"
    sig = hmac.new(settings.secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{body}.{sig}".encode()).decode()


def read_token(token: str) -> int | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, exp, sig = raw.split(".")
    except Exception:  # noqa: BLE001 - any malformed token is simply invalid
        return None
    good = hmac.new(settings.secret.encode(), f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, good) or int(exp) < time.time():
        return None
    return int(uid)


def current_user(authorization: str = Header(default=""), token: str = Query(default=""),
                 db: Session = Depends(get_db)) -> User:
    raw = authorization.removeprefix("Bearer ").strip() if authorization else token
    uid = read_token(raw) if raw else None
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "未登录或登录已过期")
    return user


def membership(db: Session, group_id: int, user: User) -> Membership:
    m = db.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == user.id))
    if m is None:
        raise HTTPException(403, "你不是该小组成员")
    return m


def require_group(db: Session, group_id: int, user: User, admin: bool = False) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "小组不存在")
    m = membership(db, group_id, user)
    if admin and m.role != "admin":
        raise HTTPException(403, "需要管理员权限（管理员可编辑库存与预算）")
    return group
