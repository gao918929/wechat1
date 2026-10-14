"""Inventory freshness, snapshots for planning, and FIFO deduction."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InventoryItem
from ..wiki import Wiki

LEVEL_LABELS = {"ok": "新鲜", "near_expiry": "临期", "expired": "已过期", "not_fresh": "外观不新鲜"}


def item_grams(item: InventoryItem, wiki: Wiki) -> float | None:
    if item.weight_g is not None:
        return item.weight_g
    ing = wiki.ingredient(item.name)
    if item.quantity is not None and ing and ing.piece_g:
        return item.quantity * ing.piece_g
    return None


def freshness(item: InventoryItem, wiki: Wiki, today: date | None = None) -> dict:
    today = today or date.today()
    ing = wiki.ingredient(item.name)
    shelf_days, near_days = wiki.shelf_for(ing)
    if item.shelf_life_days:
        shelf_days = item.shelf_life_days
    start = item.purchase_date or item.added_at.date()
    expires = start + timedelta(days=shelf_days)
    days_left = (expires - today).days
    if item.freshness == "not_fresh":
        level = "not_fresh"  # visual freshness overrides the time-based estimate
    elif days_left < 0:
        level = "expired"
    elif days_left <= near_days:
        level = "near_expiry"
    else:
        level = "ok"
    return {"expires_on": expires.isoformat(), "days_left": days_left, "level": level,
            "level_label": LEVEL_LABELS[level], "shelf_days": shelf_days, "near_expiry_days": near_days,
            "date_basis": "receipt" if item.purchase_date else "added"}


def serialize(item: InventoryItem, wiki: Wiki, today: date | None = None) -> dict:
    ing = wiki.ingredient(item.name)
    grams = item_grams(item, wiki)
    weight_text = ""
    if grams is not None:
        weight_text = f"约 {grams:.0f} g" if item.is_estimated or item.weight_g is None else f"{grams:.0f} g"
        if item.is_estimated:
            weight_text += "（估算）"
    return {
        "id": item.id, "name": item.name, "canonical": ing.name if ing else None, "category": item.category,
        "quantity": item.quantity, "weight_g": item.weight_g, "grams": grams, "weight_text": weight_text,
        "is_estimated": item.is_estimated, "estimate_note": item.estimate_note,
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "added_at": item.added_at.isoformat(), "source": item.source, "price_paid": item.price_paid,
        "freshness": freshness(item, wiki, today), "needs_weight": grams is None,
    }


def active_items(db: Session, group_id: int) -> list[InventoryItem]:
    return list(db.scalars(select(InventoryItem).where(
        InventoryItem.group_id == group_id, InventoryItem.status == "active")).all())


def snapshot(db: Session, group_id: int, wiki: Wiki, today: date | None = None) -> list[dict]:
    """Aggregate active inventory by canonical ingredient for the planning agents."""
    agg: dict[str, dict] = {}
    for item in active_items(db, group_id):
        f = freshness(item, wiki, today)
        if f["level"] == "expired":
            continue
        ing = wiki.ingredient(item.name)
        key = ing.name if ing else item.name
        grams = item_grams(item, wiki)
        cur = agg.setdefault(key, {"name": key, "grams": 0.0, "pieces": 0.0, "days_left": f["days_left"],
                                   "level": f["level"], "estimated": False, "known": ing is not None,
                                   "item_ids": []})
        cur["grams"] += grams or 0.0
        cur["pieces"] += item.quantity or 0.0
        cur["estimated"] = cur["estimated"] or item.is_estimated or grams is None
        cur["item_ids"].append(item.id)
        rank = {"not_fresh": 0, "near_expiry": 1, "ok": 2}
        if f["days_left"] < cur["days_left"]:
            cur["days_left"] = f["days_left"]
        if rank.get(f["level"], 2) < rank.get(cur["level"], 2):
            cur["level"] = f["level"]
    return sorted(agg.values(), key=lambda x: x["days_left"])


def deduct(db: Session, group_id: int, name: str, wiki: Wiki, grams: float | None = None,
           quantity: float | None = None) -> list[dict]:
    """Consume an ingredient first-expiring-first. Returns the per-item changes."""
    canon = wiki.resolve(name) or name
    ing = wiki.ingredients.get(canon)
    if grams is None and quantity is not None and ing and ing.piece_g:
        grams = quantity * ing.piece_g
    items = [i for i in active_items(db, group_id) if (wiki.resolve(i.name) or i.name) == canon]
    items.sort(key=lambda i: freshness(i, wiki)["days_left"])
    changes = []
    for item in items:
        if grams is not None:
            if grams <= 0:
                break
            have = item_grams(item, wiki)
            if have is None:
                continue
            take = min(have, grams)
            grams -= take
            left = have - take
            if item.weight_g is None and item.quantity is not None and ing and ing.piece_g:
                item.quantity = round(left / ing.piece_g, 2)
            else:
                item.weight_g = round(left, 1)
                if item.quantity is not None and ing and ing.piece_g:
                    item.quantity = round(left / ing.piece_g, 2)
            if left <= 1:
                item.status = "consumed"
            changes.append({"item_id": item.id, "name": item.name, "taken_g": round(take, 1), "left_g": round(left, 1)})
        elif quantity is not None:
            if quantity <= 0:
                break
            have_q = item.quantity or 0
            take_q = min(have_q, quantity)
            quantity -= take_q
            item.quantity = have_q - take_q
            if item.quantity <= 0:
                item.status = "consumed"
            changes.append({"item_id": item.id, "name": item.name, "taken_qty": take_q, "left_qty": item.quantity})
    return changes
