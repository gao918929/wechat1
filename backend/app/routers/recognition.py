"""Photo recognition → editable item-list card → confirm into inventory / ledger / meal records."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import current_user, membership, require_group
from ..config import settings
from ..db import get_db
from ..llm import new_client
from ..models import Expense, ExpenseItem, MealPlan, MealRecord, PriceRecord, Recognition, Upload, User
from ..realtime import hub
from ..services import inventory as inv
from ..services import twin as twin_service
from ..services.chat import card_ops
from ..services.nutrition import add_nutrition
from ..services.pricing import expense_category, price_history
from ..services.recognition import apply_card_ops, recognize
from ..wiki import get_wiki
from .inventory import add_items

router = APIRouter(prefix="/api", tags=["recognition"])
MAX_IMAGE = 8 * 1024 * 1024
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def rec_out(r: Recognition) -> dict:
    return {"id": r.id, "kind": r.kind, "status": r.status, "group_id": r.group_id, "card": r.card,
            "message": r.message, "upload_id": r.upload_id, "created_at": r.created_at.isoformat()}


def save_upload(db: Session, user: User, group_id: int, data: bytes, mime: str, sensitive: bool) -> Upload:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4().hex}{ALLOWED.get(mime, '.jpg')}"
    path.write_bytes(data)
    up = Upload(user_id=user.id, group_id=group_id, path=str(path), mime=mime, sensitive=sensitive)
    db.add(up)
    db.flush()
    return up


@router.post("/recognitions")
async def create_recognition(file: UploadFile = File(...), kind: str = Form(...), group_id: int = Form(...),
                             hint: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind not in ("ingredients", "receipt", "meal"):
        raise HTTPException(400, "kind 必须是 ingredients / receipt / meal")
    group = require_group(db, group_id, user)
    data = await file.read()
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "图片不能超过 8MB")
    mime = file.content_type if file.content_type in ALLOWED else "image/jpeg"
    up = save_upload(db, user, group.id, data, mime, sensitive=kind == "receipt")
    wiki = get_wiki()
    ut = twin_service.get_twin(db, "user", user.id)
    card, raw = await recognize(kind, data, mime, wiki, new_client(), twin_data=ut.data,
                                history=price_history(db, group.id, wiki), hint=hint[:100])
    rec = Recognition(user_id=user.id, group_id=group.id, kind=kind, upload_id=up.id, card=card, raw=raw,
                      status="pending", message=card.get("message", ""))
    db.add(rec)
    db.commit()
    return rec_out(rec)


@router.post("/recognitions/manual")
def manual_recognition(kind: str = Form(...), group_id: int = Form(...), user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """An empty card (no photo) that the user fills in by chat or tap-to-edit."""
    if kind not in ("ingredients", "receipt", "meal"):
        raise HTTPException(400, "kind 无效")
    require_group(db, group_id, user)
    card = {"kind": kind, "items": [], "message": ""}
    if kind == "meal":
        card["context"] = "home"
    rec = Recognition(user_id=user.id, group_id=group_id, kind=kind, card=card, status="pending")
    db.add(rec)
    db.commit()
    return rec_out(rec)


def _get(db: Session, rid: int, user: User) -> Recognition:
    rec = db.get(Recognition, rid)
    if rec is None:
        raise HTTPException(404, "识别记录不存在")
    membership(db, rec.group_id, user)
    return rec


@router.get("/recognitions/{rid}")
def get_recognition(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return rec_out(_get(db, rid, user))


class CardPatch(BaseModel):
    ops: list[dict] = Field(default_factory=list)
    context: str | None = Field(None, pattern="^(home|out)$")
    merchant: str | None = None
    total: float | None = None
    date: str | None = None


def _record_corrections(db: Session, user: User, rec: Recognition, corrections: list[dict]) -> None:
    for c in corrections:
        twin_service.record(db, user.id, rec.group_id, "correction", c)


@router.api_route("/recognitions/{rid}", methods=["PATCH", "PUT"])
def patch_recognition(rid: int, body: CardPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = _get(db, rid, user)
    if rec.status != "pending":
        raise HTTPException(400, "已确认的卡片不能再修改")
    card, done, corrections = apply_card_ops(rec.card, body.ops, get_wiki())
    for k in ("context", "merchant", "total", "date"):
        if getattr(body, k) is not None:
            card[k] = getattr(body, k)
    rec.card = card
    _record_corrections(db, user, rec, corrections)
    db.commit()
    return {**rec_out(rec), "applied": done}


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


@router.post("/recognitions/{rid}/chat")
async def chat_recognition(rid: int, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """“把白菜改成400克” / “这不是娃娃菜，是小白菜” → edits on the item-list card."""
    rec = _get(db, rid, user)
    if rec.status != "pending":
        raise HTTPException(400, "已确认的卡片不能再修改")
    wiki = get_wiki()
    ops, parser = await card_ops(body.text, rec.card, wiki, new_client())
    card, done, corrections = apply_card_ops(rec.card, ops, wiki)
    rec.card = card
    _record_corrections(db, user, rec, corrections)
    db.commit()
    return {**rec_out(rec), "applied": done, "ops": ops, "parser": parser,
            "message": "；".join(done) if done else "没有理解要修改什么，可以说“把白菜改成400克”"}


class ConfirmIn(BaseModel):
    item_ids: list[int] | None = None  # include these (also low-confidence ones); default: all status=ok
    add_to_inventory: bool = True  # receipts
    my_share: float = Field(1.0, gt=0, le=10)  # meal: servings I ate
    meal: str = Field("dinner", pattern="^(breakfast|lunch|dinner|snack)$")
    eaten_on: date | None = None
    plan_id: int | None = None
    plan_day: int | None = None


def _selected(card: dict, ids: list[int] | None) -> list[dict]:
    items = card.get("items", [])
    if ids is not None:
        return [i for i in items if i.get("id") in set(ids)]
    return [i for i in items if i.get("status", "ok") == "ok"]


@router.post("/recognitions/{rid}/confirm")
def confirm_recognition(rid: int, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = _get(db, rid, user)
    if rec.status != "pending":
        raise HTTPException(400, "该卡片已确认")
    wiki = get_wiki()
    card = rec.card
    items = _selected(card, body.item_ids)
    result: dict = {"kind": rec.kind}

    if rec.kind == "ingredients":
        require_group(db, rec.group_id, user, admin=True)
        rows = add_items(db, rec.group_id, [{
            "name": i["name"], "quantity": i.get("quantity"), "weight_g": i.get("weight_g"),
            "is_estimated": i.get("is_estimated", False), "estimate_note": (i.get("estimate") or {}).get("method", ""),
            "freshness": i.get("freshness", "fresh"), "source": "photo"} for i in items if i.get("name")])
        result["added"] = [r.name for r in rows]
        result["skipped"] = [i["name"] for i in card.get("items", []) if i not in items]
        hub.publish(rec.group_id, "inventory.updated", by=user.nickname, action="photo", names=result["added"])

    elif rec.kind == "receipt":
        total = card.get("total")
        if total is None:
            total = round(sum(i.get("amount") or 0 for i in items), 2)
        if not total:
            raise HTTPException(400, "请先补充实付金额")
        paid = datetime.combine(date.fromisoformat(card["date"]), datetime.now().time()) if card.get("date") else datetime.now()
        exp = Expense(group_id=rec.group_id, user_id=user.id, total_amount=float(total), paid_at=paid,
                      source=card.get("label_kind", "receipt"), merchant=card.get("merchant", ""), upload_id=rec.upload_id)
        for i in items:
            exp.items.append(ExpenseItem(name=i["name"], category=i.get("category") or expense_category(i["name"], wiki),
                                         quantity=i.get("quantity"), weight_g=i.get("weight_g"),
                                         unit_price=i.get("unit_price"), amount=i.get("amount"),
                                         estimated=bool(i.get("estimated"))))
            if i.get("unit_price") and not i.get("estimated") and wiki.ingredient(i["name"]):
                db.add(PriceRecord(group_id=rec.group_id, user_id=user.id, ingredient=wiki.ingredient(i["name"]).name,
                                   unit_price=float(i["unit_price"]), source=card.get("label_kind", "receipt"),
                                   recorded_at=paid))
                twin_service.record(db, user.id, rec.group_id, "purchase", {"name": i["name"], "unit_price": i["unit_price"]})
        db.add(exp)
        db.flush()
        result["expense_id"] = exp.id
        result["total"] = exp.total_amount
        if body.add_to_inventory and items:
            m = membership(db, rec.group_id, user)
            if m.role == "admin":
                rows = add_items(db, rec.group_id, [{
                    "name": i["name"], "quantity": i.get("quantity"), "weight_g": i.get("weight_g"),
                    "is_estimated": bool(i.get("estimated")), "purchase_date": paid.date(), "source": "receipt",
                    "price_paid": i.get("amount")} for i in items if wiki.ingredient(i["name"])])
                result["added_to_inventory"] = [r.name for r in rows]
                hub.publish(rec.group_id, "inventory.updated", by=user.nickname, action="receipt", names=result["added_to_inventory"])
            else:
                result["inventory_note"] = "成员无库存编辑权限，已只记账"
        hub.publish(rec.group_id, "expense.added", by=user.nickname, total=exp.total_amount)

    else:  # meal review
        context = card.get("context", "home")
        nutrition: dict = {}
        dishes = []
        for d in items:
            portion = max(0.5, float(d.get("portion") or 1))
            nutrition = add_nutrition(nutrition, d.get("nutrition_total") or {}, factor=body.my_share / portion)
            dishes.append(d["name"])
        skipped = []
        if body.plan_id and body.plan_day:
            plan = db.get(MealPlan, body.plan_id)
            if plan and plan.group_id == rec.group_id and plan.result:
                variant = next((v for v in plan.result["variants"] if v["key"] == (plan.chosen_variant or plan.result["recommended"])), None)
                day = next((d for d in (variant or {}).get("days", []) if d["day"] == body.plan_day), None)
                meal = next((m for m in (day or {}).get("meals", []) if m["meal"] == body.meal), None)
                if meal:
                    skipped = [x["name"] for x in meal["dishes"] if x["name"] not in dishes]
        record = MealRecord(user_id=user.id, group_id=rec.group_id, eaten_on=body.eaten_on or date.today(), meal=body.meal,
                            context=context, dishes=dishes, nutrition=nutrition, plan_id=body.plan_id, upload_id=rec.upload_id)
        db.add(record)
        changes = []
        if context == "home":  # eating out only records intake; inventory baseline is untouched
            for d in items:
                for ing in d.get("ingredients", []):
                    if ing.get("grams"):
                        changes += inv.deduct(db, rec.group_id, ing["name"], wiki, grams=ing["grams"])
            hub.publish(rec.group_id, "inventory.updated", by=user.nickname, action="meal")
        twin_service.record(db, user.id, rec.group_id, "meal", {"dishes": dishes, "context": context,
                                                                 "skipped_planned": skipped})
        result.update(context=context, nutrition=nutrition, inventory_changes=changes, deviation=skipped)

    rec.status = "confirmed"
    db.commit()
    return result


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    up = db.get(Upload, upload_id)
    if up is None:
        raise HTTPException(404, "图片不存在")
    if up.user_id != user.id:
        if up.group_id is None:
            raise HTTPException(403, "无权查看")
        membership(db, up.group_id, user)  # receipts stay inside the group, never shared externally
    if not Path(up.path).is_file():
        raise HTTPException(404, "图片已删除")
    return FileResponse(up.path, media_type=up.mime)
