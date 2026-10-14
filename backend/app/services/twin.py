"""Dietary digital twins: event-sourced personal and group profiles.

All learning signals are stored as ``FeedbackEvent`` rows; a twin refresh (weekly, or on demand)
recomputes the profile from those events plus the owner's manual edits, so the twin is always
reproducible and owners can see exactly what it learned.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Expense, FeedbackEvent, Group, Membership, Twin, User
from ..wiki import Wiki
from .estimation import update_calibration

REFRESH_INTERVAL = timedelta(days=7)
LOOKBACK = timedelta(days=180)


def get_twin(db: Session, owner_type: str, owner_id: int) -> Twin:
    twin = db.scalar(select(Twin).where(Twin.owner_type == owner_type, Twin.owner_id == owner_id))
    if twin is None:
        twin = Twin(owner_type=owner_type, owner_id=owner_id, data={"manual": {}}, version=0,
                    updated_at=datetime.now() - REFRESH_INTERVAL * 2)
        db.add(twin)
        db.flush()
    return twin


def record(db: Session, user_id: int, group_id: int | None, kind: str, payload: dict) -> FeedbackEvent:
    ev = FeedbackEvent(user_id=user_id, group_id=group_id, kind=kind, payload=payload)
    db.add(ev)
    return ev


def _aggregate(events: list[FeedbackEvent], wiki: Wiki) -> dict:
    dish_scores: Counter = Counter()
    ing_scores: Counter = Counter()
    subs: Counter = Counter()
    variants: Counter = Counter()
    favorites: list[str] = []
    recent: list[str] = []
    data: dict = {"calibration": {}}
    price_ratios: list[float] = []
    diners_by_weekday: dict[int, list[int]] = {}
    renames: Counter = Counter()

    for ev in sorted(events, key=lambda e: e.created_at):
        p = ev.payload or {}
        k = ev.kind
        if k == "rating":
            delta = (float(p.get("score", 3)) - 3) / 2
            for dish in p.get("dishes") or ([p["dish"]] if p.get("dish") else []):
                dish_scores[dish] += delta
        elif k == "favorite":
            dish_scores[p["dish"]] += 2
            if p["dish"] not in favorites:
                favorites.append(p["dish"])
        elif k == "unfavorite":
            dish_scores[p["dish"]] -= 2
            if p["dish"] in favorites:
                favorites.remove(p["dish"])
        elif k == "delete":
            dish_scores[p["dish"]] -= 1.5
        elif k == "substitute":
            if p.get("from_dish") and p.get("to_dish"):
                dish_scores[p["from_dish"]] -= 1
                dish_scores[p["to_dish"]] += 1
            if p.get("from") and p.get("to"):
                a, b = wiki.resolve(p["from"]) or p["from"], wiki.resolve(p["to"]) or p["to"]
                subs[(a, b)] += 1
                ing_scores[a] -= 0.5
                ing_scores[b] += 0.5
        elif k == "correction":
            if p.get("estimated_g") and p.get("actual_g"):
                update_calibration(data, wiki.resolve(p.get("name", "")) or p.get("name", ""), p["estimated_g"], p["actual_g"])
            if p.get("from_name") and p.get("to_name"):
                renames[(p["from_name"], p["to_name"])] += 1
        elif k == "choose_variant":
            variants[p.get("variant", "balanced")] += 1
        elif k == "meal":
            for dish in p.get("dishes") or []:
                dish_scores[dish] += 0.3
                recent.insert(0, dish)
            for dish in p.get("skipped_planned") or []:
                dish_scores[dish] -= 0.3
        elif k == "purchase":
            ing = wiki.ingredient(p.get("name", ""))
            if ing and ing.price_mid and p.get("unit_price"):
                price_ratios.append(p["unit_price"] / ing.price_mid)
        elif k == "diners":
            diners_by_weekday.setdefault(ev.created_at.weekday(), []).append(int(p.get("count", 1)))

    ratio = sum(price_ratios) / len(price_ratios) if price_ratios else None
    sensitivity = None if ratio is None else ("high" if ratio < 0.9 else "low" if ratio > 1.15 else "mid")
    data.update({
        "dish_scores": {k: round(v, 2) for k, v in dish_scores.items() if abs(v) >= 0.05},
        "ingredient_scores": {k: round(v, 2) for k, v in ing_scores.items() if abs(v) >= 0.05},
        "substitutions": [{"from": a, "to": b, "count": n} for (a, b), n in subs.most_common(20)],
        "variant_choices": dict(variants), "favorites": favorites, "recent_dishes": list(dict.fromkeys(recent))[:21],
        "price_ratio": round(ratio, 2) if ratio else None, "price_sensitivity": sensitivity,
        "diner_pattern": {str(d): round(sum(v) / len(v), 1) for d, v in diners_by_weekday.items()},
        "learned_renames": [{"from": a, "to": b, "count": n} for (a, b), n in renames.most_common(10)],
        "feedback_count": len(events),
    })
    return data


def _apply_manual(data: dict, manual: dict) -> dict:
    data["manual"] = manual
    scores = data.setdefault("ingredient_scores", {})
    for name in manual.get("likes", []):
        scores[name] = scores.get(name, 0) + 2
    for name in manual.get("dislikes", []):
        scores[name] = scores.get(name, 0) - 2
    data["style_notes"] = manual.get("notes", "")
    return data


def refresh_user_twin(db: Session, user: User, wiki: Wiki) -> Twin:
    twin = get_twin(db, "user", user.id)
    since = datetime.now() - LOOKBACK
    events = list(db.scalars(select(FeedbackEvent).where(FeedbackEvent.user_id == user.id,
                                                         FeedbackEvent.created_at >= since)).all())
    data = _apply_manual(_aggregate(events, wiki), (twin.data or {}).get("manual", {}))
    data["profile"] = {"likes": user.likes, "avoidances": user.avoidances, "allergens": user.allergens,
                       "goal": user.goal, "dietary_groups": user.dietary_groups, "max_spicy": user.max_spicy}
    for ev in events:
        ev.processed = True
    twin.data, twin.version, twin.updated_at = data, twin.version + 1, datetime.now()
    return twin


def refresh_group_twin(db: Session, group: Group, wiki: Wiki) -> Twin:
    twin = get_twin(db, "group", group.id)
    since = datetime.now() - LOOKBACK
    events = list(db.scalars(select(FeedbackEvent).where(FeedbackEvent.group_id == group.id,
                                                         FeedbackEvent.created_at >= since)).all())
    data = _apply_manual(_aggregate(events, wiki), (twin.data or {}).get("manual", {}))
    members = [m.user for m in group.memberships]
    avoid_sets = [set(u.avoidances or []) for u in members]
    like_sets = [set(u.likes or []) for u in members]
    data["members"] = [{"id": u.id, "name": u.nickname or f"成员{u.id}", "avoid": u.avoidances, "likes": u.likes,
                        "allergens": u.allergens} for u in members]
    data["union_avoid"] = sorted(set().union(*avoid_sets)) if avoid_sets else []
    data["union_allergens"] = sorted(set().union(*[set(u.allergens or []) for u in members])) if members else []
    data["intersection_likes"] = sorted(set.intersection(*like_sets)) if like_sets else []
    expenses = db.scalars(select(Expense).where(Expense.group_id == group.id, Expense.paid_at >= since)).all()
    if expenses:
        weeks = max(1.0, (datetime.now() - min(e.paid_at for e in expenses)).days / 7)
        data["budget_habits"] = {
            "avg_weekly_spend": round(sum(e.total_amount for e in expenses) / weeks, 2),
            "channels": [m for m, _ in Counter(e.merchant for e in expenses if e.merchant).most_common(3)],
            "budget_mode": group.budget_mode,
        }
    twin.data, twin.version, twin.updated_at = data, twin.version + 1, datetime.now()
    return twin


def ensure_fresh(db: Session, user: User, group: Group, wiki: Wiki, force: bool = False) -> tuple[Twin, Twin]:
    """Weekly update cycle: recompute twins older than 7 days (or when forced)."""
    ut, gt = get_twin(db, "user", user.id), get_twin(db, "group", group.id)
    now = datetime.now()
    if force or now - ut.updated_at >= REFRESH_INTERVAL:
        ut = refresh_user_twin(db, user, wiki)
    if force or now - gt.updated_at >= REFRESH_INTERVAL:
        gt = refresh_group_twin(db, group, wiki)
    return ut, gt


def planning_view(user_twin: Twin, group_twin: Twin) -> dict:
    """Merge personal + group twins for the Iterative Optimization Agent."""
    u, g = user_twin.data or {}, group_twin.data or {}
    out: dict = {}
    for key in ("dish_scores", "ingredient_scores"):
        merged: dict[str, float] = dict(g.get(key, {}))
        for k, v in u.get(key, {}).items():
            merged[k] = round(merged.get(k, 0) + v, 2)
        out[key] = merged
    subs: dict[tuple, int] = {}
    for s in g.get("substitutions", []) + u.get("substitutions", []):
        subs[(s["from"], s["to"])] = subs.get((s["from"], s["to"]), 0) + s["count"]
    out["substitutions"] = [{"from": a, "to": b, "count": n} for (a, b), n in subs.items()]
    vc = Counter(g.get("variant_choices", {})) + Counter(u.get("variant_choices", {}))
    out["variant_choices"] = dict(vc)
    out["favorites"] = list(dict.fromkeys(u.get("favorites", []) + g.get("favorites", [])))
    out["recent_dishes"] = list(dict.fromkeys(g.get("recent_dishes", []) + u.get("recent_dishes", [])))[:21]
    out["calibration"] = {**g.get("calibration", {}), **u.get("calibration", {})}
    out["price_sensitivity"] = u.get("price_sensitivity") or g.get("price_sensitivity")
    out["diner_pattern"] = g.get("diner_pattern", {})
    out["feedback_count"] = u.get("feedback_count", 0) + g.get("feedback_count", 0)
    out["style_notes"] = u.get("style_notes", "")
    out["version"] = f"{user_twin.version}.{group_twin.version}"
    return out


def can_view_group_twin(group: Group, user_id: int) -> bool:
    if group.owner_id == user_id or group.twin_visibility == "all":
        return any(m.user_id == user_id for m in group.memberships)
    if group.twin_visibility == "selected":
        return user_id in (group.twin_visible_member_ids or [])
    return False


def is_member(db: Session, group_id: int, user_id: int) -> bool:
    return db.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == user_id)) is not None
