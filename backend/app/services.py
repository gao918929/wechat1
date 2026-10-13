import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from fastapi import HTTPException
from .domain import known, nutrition, consume
from .store import digest, packed, now


def idempotent(store, db, kind, group, owner, request_id, body, prefix=None):
    key = digest(f"{kind}:{group}:{owner}:{prefix or request_id}")
    found = db.execute("SELECT id FROM entities WHERE id=?", (key,)).fetchone()
    if found:
        row = store.get(db, key, kind)
        if row.get("fingerprint") != digest(packed(body)):
            raise HTTPException(409, "Request ID was already used for different data")
        return key, row
    return key, None


def confirm_draft(store, db, draft_id, group, user, kind):
    draft = store.get(db, draft_id, "draft")
    if draft["owner_id"] != user or draft["group_id"] != group or draft["kind"] != kind:
        raise HTTPException(403, "Draft access denied")
    if draft.get("confirmed"):
        raise HTTPException(409, "Draft was already confirmed")
    draft["confirmed"] = True
    store.put(db, "draft", group, user, draft, draft_id, draft["version"])


def receipt(store, db, group, user, body):
    key, existing = idempotent(store, db, "receipt", group, user, body["request_id"], body, body.get("draft_id"))
    if existing:
        return existing
    if date.fromisoformat(body["purchased_on"]) > date.today():
        raise HTTPException(422, "Purchase date cannot be in the future")
    if body.get("draft_id"):
        confirm_draft(store, db, body["draft_id"], group, user, "receipt")
    line_sum = sum(i["line_cents"] or 0 for i in body["items"])
    all_lines = all(i["line_cents"] is not None for i in body["items"])
    # Actual paid amount is immutable. Discounts are proportionally allocated only
    # if every item has a known line amount; partial data never becomes exact history.
    allocated = []
    if all_lines and line_sum > 0:
        allocated = [body["paid_cents"] * i["line_cents"] // line_sum for i in body["items"]]
        remainder = body["paid_cents"] - sum(allocated)
        ranking = sorted(range(len(allocated)), key=lambda i: -(body["paid_cents"] * body["items"][i]["line_cents"] % line_sum))
        for i in ranking[:remainder]:
            allocated[i] += 1
    category_totals = defaultdict(int)
    for index, item in enumerate(body["items"]):
        food = known(item["ingredient_id"])
        if item["expires_on"] < body["purchased_on"]:
            raise HTTPException(422, "Expiry date precedes purchase date")
        store.put(db, "inventory", group, user,
            {"ingredient_id": item["ingredient_id"], "grams": item["grams"], "purchased_on": body["purchased_on"],
             "expires_on": item["expires_on"], "freshness": "unknown", "estimated": item["estimated"], "receipt_id": key})
        if allocated:
            item["allocated_paid_cents"] = allocated[index]
            category_totals[food["category"]] += allocated[index]
            if not item["estimated"]:
                store.put(db, "price", group, user, {"ingredient_id": item["ingredient_id"],
                    "cents_per_kg": allocated[index] * 1000 / item["grams"], "estimated": False,
                    "source": "Actual receipt, discounts allocated proportionally", "receipt_id": key})
    if not allocated:
        category_totals["unallocated"] = body["paid_cents"]
    # Hash the incoming data before enrichments for reliable replay comparisons.
    incoming = {**body, "items": [{k:v for k,v in i.items() if k != "allocated_paid_cents"} for i in body["items"]]}
    row = store.put(db, "receipt", group, user, {**body, "category_totals": dict(category_totals),
                    "fingerprint": digest(packed(incoming)), "immutable": True}, key)
    store.emit(db, group, user, "receipt_created", {})
    store.emit(db, group, user, "inventory_changed", {})
    return row


def record_meal(store, db, group, user, body):
    key, existing = idempotent(store, db, "meal", group, user, body["request_id"], body, body.get("draft_id"))
    if existing:
        return existing
    if date.fromisoformat(body["eaten_on"]) > date.today():
        raise HTTPException(422, "Meal date cannot be in the future")
    if body["context"] == "out" and body["consumption"]:
        raise HTTPException(422, "Dining out must not change refrigerator inventory")
    if body.get("draft_id"):
        confirm_draft(store, db, body["draft_id"], group, user, "meal")
    totals = nutrition(body["items"])
    if body["context"] == "home" and body["consumption"]:
        consume(store, db, group, user, body["consumption"])
    result = store.put(db, "meal", group, user, {**body, "nutrition": totals, "sources": sorted({known(i["ingredient_id"])["source"] for i in body["items"]}), "fingerprint": digest(packed(body))}, key)
    store.emit(db, group, user, "meals_changed", {})
    return result


def build_twin(store, db, group, user, collective=False):
    key = digest("group-twin:" + group) if collective else digest("personal-twin:" + user)
    rows = db.execute("SELECT id FROM entities WHERE id=?", (key,)).fetchone()
    old = store.get(db, key, "twin") if rows else None
    if old and datetime.fromisoformat(old["updated_at"]) > datetime.now(timezone.utc) - timedelta(days=7):
        return old
    feedback = store.items(db, "feedback", group if collective else None, None if collective else user)
    if collective:
        feedback = [f for f in feedback if f.get("shared")]
    selections = Counter(f.get("mode") for f in feedback if f["action"] == "select" and f.get("mode"))
    substitutions = [f["text"] for f in feedback if f["action"] == "substitute"][:30]
    receipts = store.items(db, "receipt", group if collective else None, None if collective else user)
    total = sum(r["paid_cents"] for r in receipts)
    name = "group" if collective else "personal"
    body = {"type": name, "selection_counts": dict(selections), "substitutions": substitutions,
            "feedback_count": len(feedback), "purchase_count": len(receipts),
            "average_purchase_cents": round(total / len(receipts)) if receipts else None,
            "recent_feedback": [{k:f[k] for k in ("action", "text", "rating") if k in f} for f in feedback[:20]],
            "next_refresh": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "privacy": "Only explicitly shared preference feedback is used in group memory" if collective else "Owner only"}
    owner = db.execute("SELECT owner FROM groups WHERE id=?", (group,)).fetchone()[0] if collective else user
    return store.put(db, "twin", group if collective else user, owner, body, key)
