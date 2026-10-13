"""Price memory, cost-calculation price priority and tiered unit-price completion."""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PriceRecord
from ..wiki import Wiki

EXPENSE_CATEGORY = {
    "vegetables": "vegetables", "meat_eggs": "meat_eggs", "seafood": "seafood",
    "staples": "staples", "soy_dairy": "staples", "seasonings": "seasonings",
}
EXPENSE_CATEGORY_LABELS = {"vegetables": "蔬菜", "meat_eggs": "肉蛋", "seafood": "水产", "staples": "主食",
                           "seasonings": "调味", "other": "其他"}


def expense_category(name: str, wiki: Wiki) -> str:
    ing = wiki.ingredient(name)
    return EXPENSE_CATEGORY.get(ing.section, "other") if ing else "other"


def price_history(db: Session, group_id: int, wiki: Wiki, days: int = 90) -> dict[str, float]:
    """Median actual unit price (CNY/kg) per canonical ingredient over the last ``days``."""
    since = datetime.now() - timedelta(days=days)
    rows = db.scalars(select(PriceRecord).where(PriceRecord.group_id == group_id,
                                                PriceRecord.recorded_at >= since)).all()
    bucket: dict[str, list[float]] = {}
    for r in rows:
        canon = wiki.resolve(r.ingredient) or r.ingredient
        bucket.setdefault(canon, []).append(r.unit_price)
    return {k: round(median(v), 2) for k, v in bucket.items()}


def unit_price(name: str, history: dict[str, float], wiki: Wiki) -> dict:
    """Priority: historical actual price → reference price (labelled 估算)."""
    canon = wiki.resolve(name) or name
    if canon in history:
        return {"unit_price": history[canon], "estimated": False, "source": "history"}
    ing = wiki.ingredients.get(canon)
    if ing and ing.price_mid:
        return {"unit_price": ing.price_mid, "estimated": True, "source": "reference"}
    return {"unit_price": None, "estimated": True, "source": "unknown"}


def complete_item(item: dict, wiki: Wiki, history: dict[str, float] | None = None) -> dict:
    """Fill in a receipt line's missing unit price / weight following the tiered rules.

    ``item`` keys: name, quantity (pieces), weight_g, unit_price (CNY/kg), amount (CNY).
    """
    out = dict(item)
    notes = []
    ing = wiki.ingredient(item.get("name", ""))
    amount, weight, qty, price = (item.get(k) for k in ("amount", "weight_g", "quantity", "unit_price"))
    estimated = bool(item.get("estimated"))

    if price is None and amount and weight:
        price = round(amount / (weight / 1000), 2)
        notes.append("单价=总价÷重量")
    elif price is None and amount and qty and ing and ing.piece_g:
        weight = round(qty * ing.piece_g)
        price = round(amount / (weight / 1000), 2)
        estimated = True
        notes.append(f"按单个参考重量 {ing.piece_g:g} g 估算重量后反推单价（估算）")
    elif price is None:
        ref = unit_price(item.get("name", ""), history or {}, wiki)
        if ref["unit_price"] is not None:
            price = ref["unit_price"]
            estimated = estimated or ref["estimated"]
            notes.append("使用历史成交价" if ref["source"] == "history" else "使用参考价（估算）")
    if weight is None and price and amount:
        weight = round(amount / price * 1000)
        estimated = True
        notes.append("重量=总价÷单价（估算）")
    if amount is None and price and weight:
        amount = round(price * weight / 1000, 2)
        estimated = True
    out.update({"unit_price": price, "weight_g": weight, "amount": amount, "estimated": estimated,
                "note": "；".join(notes), "category": expense_category(item.get("name", ""), wiki),
                "canonical": ing.name if ing else None})
    return out
