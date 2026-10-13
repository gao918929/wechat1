"""Smart fridge inventory: list with freshness alerts, manual/chat entry, consumption."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import current_user, membership, require_group
from ..db import get_db
from ..llm import new_client
from ..models import InventoryItem, User
from ..realtime import hub
from ..services import inventory as inv
from ..services.chat import inventory_ops
from ..wiki import get_wiki

router = APIRouter(prefix="/api", tags=["inventory"])


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    quantity: float | None = Field(None, ge=0)
    weight_g: float | None = Field(None, ge=0)
    is_estimated: bool = False
    estimate_note: str = ""
    purchase_date: date | None = None
    shelf_life_days: int | None = Field(None, ge=1, le=3650)
    freshness: str = Field("fresh", pattern="^(fresh|not_fresh)$")
    source: str = "manual"
    price_paid: float | None = None


class ItemsIn(BaseModel):
    items: list[ItemIn]


class ItemPatch(BaseModel):
    name: str | None = None
    quantity: float | None = Field(None, ge=0)
    weight_g: float | None = Field(None, ge=0)
    purchase_date: date | None = None
    shelf_life_days: int | None = Field(None, ge=1, le=3650)
    freshness: str | None = Field(None, pattern="^(fresh|not_fresh)$")


class ConsumeIn(BaseModel):
    name: str | None = None
    quantity: float | None = Field(None, gt=0)
    weight_g: float | None = Field(None, gt=0)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def add_items(db: Session, group_id: int, items: list[dict]) -> list[InventoryItem]:
    wiki = get_wiki()
    rows = []
    for it in items:
        ing = wiki.ingredient(it["name"])
        row = InventoryItem(group_id=group_id, name=ing.name if ing else it["name"],
                            category=ing.section if ing else "", quantity=it.get("quantity"), weight_g=it.get("weight_g"),
                            is_estimated=bool(it.get("is_estimated")), estimate_note=it.get("estimate_note", "")[:128],
                            purchase_date=it.get("purchase_date"), shelf_life_days=it.get("shelf_life_days"),
                            freshness=it.get("freshness") or "fresh", source=it.get("source") or "manual",
                            price_paid=it.get("price_paid"))
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


@router.get("/groups/{gid}/inventory")
def list_inventory(gid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    wiki = get_wiki()
    items = [inv.serialize(i, wiki) for i in inv.active_items(db, gid)]
    items.sort(key=lambda x: ({"not_fresh": 0, "expired": 1, "near_expiry": 2, "ok": 3}[x["freshness"]["level"]],
                              x["freshness"]["days_left"]))
    alerts = [{"id": i["id"], "name": i["name"], "level": i["freshness"]["level"], "label": i["freshness"]["level_label"],
               "days_left": i["freshness"]["days_left"]} for i in items if i["freshness"]["level"] != "ok"]
    return {"items": items, "alerts": alerts, "needs_weight": [i["name"] for i in items if i["needs_weight"]]}


@router.post("/groups/{gid}/inventory")
def create_items(gid: int, body: ItemsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user, admin=True)
    rows = add_items(db, gid, [i.model_dump() for i in body.items])
    db.commit()
    hub.publish(gid, "inventory.updated", by=user.nickname, action="add", names=[r.name for r in rows])
    wiki = get_wiki()
    return [inv.serialize(r, wiki) for r in rows]


@router.api_route("/inventory/{item_id}", methods=["PATCH", "PUT"])
def patch_item(item_id: int, body: ItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(404, "库存不存在")
    require_group(db, item.group_id, user, admin=True)
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(item, k, v)
    if "weight_g" in data:
        item.is_estimated = False
    db.commit()
    hub.publish(item.group_id, "inventory.updated", by=user.nickname, action="edit", names=[item.name])
    return inv.serialize(item, get_wiki())


@router.delete("/inventory/{item_id}")
def delete_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(404, "库存不存在")
    require_group(db, item.group_id, user, admin=True)
    item.status = "discarded"
    db.commit()
    hub.publish(item.group_id, "inventory.updated", by=user.nickname, action="remove", names=[item.name])
    return {"ok": True}


@router.post("/inventory/{item_id}/consume")
def consume_item(item_id: int, body: ConsumeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if item is None or item.status != "active":
        raise HTTPException(404, "库存不存在")
    membership(db, item.group_id, user)  # members may mark consumption
    wiki = get_wiki()
    if body.quantity is None and body.weight_g is None:
        item.status = "consumed"
        changes = [{"item_id": item.id, "name": item.name, "all": True}]
    else:
        changes = inv.deduct(db, item.group_id, item.name, wiki, grams=body.weight_g, quantity=body.quantity)
    db.commit()
    hub.publish(item.group_id, "inventory.updated", by=user.nickname, action="consume", names=[item.name])
    return {"changes": changes}


@router.post("/groups/{gid}/inventory/consume")
def consume_many(gid: int, body: list[ConsumeIn], user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_group(db, gid, user)
    wiki = get_wiki()
    changes = []
    for c in body:
        if c.name:
            changes += inv.deduct(db, gid, c.name, wiki, grams=c.weight_g, quantity=c.quantity)
    db.commit()
    hub.publish(gid, "inventory.updated", by=user.nickname, action="consume", names=[c.name for c in body])
    return {"changes": changes}


@router.post("/groups/{gid}/inventory/chat")
async def inventory_chat(gid: int, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """“冰箱里还有两个鸡蛋和半颗白菜” / “今天用了两个鸡蛋” → inventory operations."""
    group = require_group(db, gid, user)
    wiki = get_wiki()
    parsed = await inventory_ops(body.text, wiki, new_client())
    if parsed["intent"] == "unknown":
        return {"ok": False, "message": "没有识别到食材，可以说“冰箱里还有两个鸡蛋”或“今天用了两个鸡蛋”", "parsed": parsed}
    if parsed["intent"] != "consume":
        require_group(db, group.id, user, admin=True)
    applied = []
    for it in parsed["items"]:
        if parsed["intent"] == "consume":
            ch = inv.deduct(db, gid, it["name"], wiki, grams=it.get("weight_g"), quantity=it.get("quantity"))
            applied.append(f"消耗 {it['name']}" + ("" if ch else "（库存中没有，已忽略）"))
        elif parsed["intent"] == "remove":
            for row in inv.active_items(db, gid):
                if (wiki.resolve(row.name) or row.name) == it["name"]:
                    row.status = "discarded"
            applied.append(f"移除 {it['name']}")
        else:
            if parsed["intent"] == "set":
                for row in inv.active_items(db, gid):
                    if (wiki.resolve(row.name) or row.name) == it["name"]:
                        row.status = "consumed"
            ing = wiki.ingredient(it["name"])
            weight, estimated = it.get("weight_g"), False
            if weight is None and it.get("quantity") is not None and ing and ing.piece_g:
                weight, estimated = round(it["quantity"] * ing.piece_g), True
            add_items(db, gid, [{"name": it["name"], "quantity": it.get("quantity"), "weight_g": weight,
                                 "is_estimated": estimated, "source": "chat",
                                 "estimate_note": "按单个参考重量估算" if estimated else ""}])
            amount = f"{it['quantity']:g} 个" if it.get("quantity") is not None else (
                f"{it['weight_g']:g} g" if it.get("weight_g") else "")
            applied.append(f"{'更新为' if parsed['intent'] == 'set' else '添加'} {it['name']} {amount}".strip())
    db.commit()
    hub.publish(gid, "inventory.updated", by=user.nickname, action=parsed["intent"], names=[i["name"] for i in parsed["items"]])
    return {"ok": True, "parsed": parsed, "applied": applied}
