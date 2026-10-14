"""Expense ledger (actual amounts paid) and weekly / monthly food-expense reports."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_group
from ..db import get_db
from ..models import Expense, ExpenseItem, User
from ..realtime import hub
from ..services.pricing import EXPENSE_CATEGORY_LABELS, complete_item, price_history
from ..wiki import get_wiki

router = APIRouter(prefix="/api", tags=["expenses"])


class ExpenseItemIn(BaseModel):
    name: str
    quantity: float | None = None
    weight_g: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class ExpenseIn(BaseModel):
    total_amount: float = Field(gt=0)
    merchant: str = ""
    note: str = ""
    paid_on: date | None = None
    items: list[ExpenseItemIn] = Field(default_factory=list)


def expense_out(e: Expense) -> dict:
    return {"id": e.id, "total_amount": e.total_amount, "paid_at": e.paid_at.isoformat(), "source": e.source,
            "merchant": e.merchant, "note": e.note, "user_id": e.user_id, "upload_id": e.upload_id,
            "items": [{"name": i.name, "category": i.category, "category_label": EXPENSE_CATEGORY_LABELS.get(i.category, "其他"),
                       "quantity": i.quantity, "weight_g": i.weight_g, "unit_price": i.unit_price, "amount": i.amount,
                       "estimated": i.estimated} for i in e.items]}


@router.get("/groups/{gid}/expenses")
def list_expenses(gid: int, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    rows = db.scalars(select(Expense).where(Expense.group_id == gid).order_by(Expense.paid_at.desc()).limit(min(limit, 200))).all()
    return [expense_out(e) for e in rows]


@router.post("/groups/{gid}/expenses")
def add_expense(gid: int, body: ExpenseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    wiki = get_wiki()
    hist = price_history(db, gid, wiki)
    paid = datetime.combine(body.paid_on, datetime.now().time()) if body.paid_on else datetime.now()
    e = Expense(group_id=gid, user_id=user.id, total_amount=body.total_amount, paid_at=paid, source="manual",
                merchant=body.merchant, note=body.note)
    for it in body.items:
        c = complete_item(it.model_dump(), wiki, hist)
        e.items.append(ExpenseItem(name=c["name"], category=c["category"], quantity=c.get("quantity"),
                                   weight_g=c.get("weight_g"), unit_price=c.get("unit_price"), amount=c.get("amount"),
                                   estimated=c["estimated"]))
    db.add(e)
    db.commit()
    hub.publish(gid, "expense.added", by=user.nickname, total=e.total_amount)
    return expense_out(e)


@router.delete("/expenses/{eid}")
def delete_expense(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(Expense, eid)
    if e is None:
        raise HTTPException(404, "记录不存在")
    require_group(db, e.group_id, user, admin=e.user_id != user.id)
    db.delete(e)
    db.commit()
    return {"ok": True}


def period_range(period: str, offset: int) -> tuple[date, date]:
    today = date.today()
    if period == "month":
        y, m = today.year, today.month - offset
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1)
        end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        return start, end
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    return start, start + timedelta(days=6)


@router.get("/groups/{gid}/expenses/report")
def expense_report(gid: int, period: str = "week", offset: int = 0, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if period not in ("week", "month"):
        raise HTTPException(400, "period 为 week 或 month")
    group = require_group(db, gid, user)
    start, end = period_range(period, max(0, offset))
    rows = db.scalars(select(Expense).where(Expense.group_id == gid,
                                            Expense.paid_at >= datetime.combine(start, datetime.min.time()),
                                            Expense.paid_at <= datetime.combine(end, datetime.max.time()))).all()
    total = round(sum(e.total_amount for e in rows), 2)
    by_cat: dict[str, float] = {}
    for e in rows:
        itemized = 0.0
        for i in e.items:
            if i.amount:
                by_cat[i.category] = by_cat.get(i.category, 0) + i.amount
                itemized += i.amount
        if e.total_amount - itemized > 0.01:
            by_cat["other"] = by_cat.get("other", 0) + e.total_amount - itemized
    by_payer: dict[int, float] = {}
    for e in rows:
        by_payer[e.user_id] = by_payer.get(e.user_id, 0) + e.total_amount
    names = {m.user_id: m.user.nickname or f"成员{m.user_id}" for m in group.memberships}
    members = max(1, len(group.memberships))
    weekly_budget = (group.budget_amount * members if group.budget_mode == "per_person" else group.budget_amount) or 0
    budget = round(weekly_budget * (((end - start).days + 1) / 7), 2) if weekly_budget else None
    daily = {}
    for e in rows:
        k = e.paid_at.date().isoformat()
        daily[k] = round(daily.get(k, 0) + e.total_amount, 2)
    return {
        "period": period, "start": start.isoformat(), "end": end.isoformat(), "total": total, "count": len(rows),
        "by_category": [{"category": k, "label": EXPENSE_CATEGORY_LABELS.get(k, "其他"), "amount": round(v, 2),
                         "share": round(v / total, 3) if total else 0} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "per_person": round(total / members, 2), "members": members,
        "by_payer": [{"user_id": k, "nickname": names.get(k, str(k)), "amount": round(v, 2)} for k, v in by_payer.items()],
        "budget": budget, "budget_mode": group.budget_mode, "over_budget": bool(budget and total > budget),
        "budget_left": round(budget - total, 2) if budget else None, "daily": daily,
        "note": "记账口径为小票实付金额",
    }
