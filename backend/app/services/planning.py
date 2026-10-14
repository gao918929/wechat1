"""Assemble a PlanningContext from the database + the user's natural-language instruction."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..agents.context import Emit, PlanningContext, make_diner
from ..llm import LLMClient, LLMError
from ..models import Group, User
from ..wiki import Wiki
from . import inventory as inv_service
from . import twin as twin_service
from .nl import normalize_avoid, parse_plan_instruction
from .pricing import price_history

INTENT_PROMPT = """你是 MealAgent 中央调度器的意图解析模块。从用户的自然语言指令中抽取规划约束。
字段：height_cm, weight_kg, people(就餐人数), budget_mode("per_person"|"total"), budget_amount(元),
goal("fat_loss"|"muscle_gain"|"maintain"|"stomach"), avoid(口味忌口，食材名或标签如 spicy/seafood/fatty_meat),
allergens(过敏原), dietary_groups(从 known_groups 中选), inventory_mentions([{"name","near_expiry":bool,"quantity","weight_g"}]),
days(天数), meals(["breakfast","lunch","dinner"] 子集)。没有提到的字段不要输出。规则解析结果仅供参考。
输出 JSON 对象。"""


def user_profile(u: User) -> dict:
    return {"sex": u.sex, "age": u.age, "height_cm": u.height_cm, "weight_kg": u.weight_kg,
            "body_fat_pct": u.body_fat_pct, "activity_level": u.activity_level, "goal": u.goal,
            "dietary_groups": list(u.dietary_groups or []), "allergens": list(u.allergens or []),
            "avoidances": list(u.avoidances or []), "likes": list(u.likes or []), "max_spicy": u.max_spicy}


async def parse_instruction(text: str, wiki: Wiki, llm: LLMClient) -> dict:
    parsed = parse_plan_instruction(text or "", wiki)
    parsed["parser"] = "rules"
    if not (llm.online and (text or "").strip()):
        return parsed
    try:
        resp = await llm.chat_json(INTENT_PROMPT, {"instruction": text, "rules_parse": parsed,
                                                   "known_groups": sorted(wiki.diet_models)}, agent="orchestrator")
    except LLMError:
        return parsed
    for key in ("height_cm", "weight_kg", "budget_amount"):
        if isinstance(resp.get(key), (int, float)) and resp[key] > 0:
            parsed[key] = float(resp[key])
    for key in ("people", "days"):
        if isinstance(resp.get(key), (int, float)) and 0 < resp[key] <= 30:
            parsed[key] = int(resp[key])
    if resp.get("budget_mode") in ("per_person", "total"):
        parsed["budget_mode"] = resp["budget_mode"]
    if resp.get("goal") in ("fat_loss", "muscle_gain", "maintain", "stomach"):
        parsed["goal"] = resp["goal"]
    for key in ("avoid", "allergens"):
        vals = [normalize_avoid(str(v), wiki) for v in resp.get(key) or []]
        parsed[key] = list(dict.fromkeys(parsed.get(key, []) + [v for v in vals if v]))
    parsed["dietary_groups"] = list(dict.fromkeys(parsed.get("dietary_groups", []) + [
        g for g in resp.get("dietary_groups") or [] if g in wiki.diet_models]))
    meals = [m for m in resp.get("meals") or [] if m in ("breakfast", "lunch", "dinner")]
    if meals:
        parsed["meals"] = meals
    mentions = {m["name"]: m for m in parsed.get("inventory_mentions", [])}
    for m in resp.get("inventory_mentions") or []:
        canon = wiki.resolve(str(m.get("name", "")))
        if canon:
            cur = mentions.setdefault(canon, {"name": canon, "near_expiry": False})
            cur["near_expiry"] = cur["near_expiry"] or bool(m.get("near_expiry"))
            for k in ("quantity", "weight_g"):
                if isinstance(m.get(k), (int, float)):
                    cur[k] = m[k]
    parsed["inventory_mentions"] = list(mentions.values())
    parsed["parser"] = "llm"
    return parsed


def _mention_items(mentions: list[dict], snapshot: list[dict], wiki: Wiki) -> list[dict]:
    """Ingredients mentioned in the instruction but missing from recorded inventory are added to the
    planning snapshot (amounts labelled 估算); "快过期" mentions mark stock as near-expiry."""
    by_name = {s["name"]: s for s in snapshot}
    for m in mentions:
        ing = wiki.ingredient(m["name"])
        if ing is None:
            continue
        cur = by_name.get(ing.name)
        if cur is None:
            grams = m.get("weight_g") or ((m.get("quantity") or (6 if ing.name == "鸡蛋" else 3)) * ing.piece_g
                                          if ing.piece_g and ing.piece_g <= 600 else 500)
            shelf, near = wiki.shelf_for(ing)
            cur = {"name": ing.name, "grams": float(grams), "pieces": m.get("quantity") or 0, "days_left": shelf,
                   "level": "ok", "estimated": True, "known": True, "item_ids": [], "from_instruction": True}
            snapshot.append(cur)
            by_name[ing.name] = cur
        if m.get("near_expiry"):
            cur["days_left"] = min(cur["days_left"], 1)
            cur["level"] = "near_expiry" if cur["level"] != "not_fresh" else "not_fresh"
    return sorted(snapshot, key=lambda x: x["days_left"])


async def build_context(db: Session, user: User, group: Group, instruction: str, options: dict,
                        llm: LLMClient, wiki: Wiki, emit: Emit) -> PlanningContext:
    parsed = await parse_instruction(instruction, wiki, llm)
    overrides = set(options.get("overrides") or [])

    members = sorted((m.user for m in group.memberships), key=lambda u: (u.id != user.id, u.id))
    if options.get("diner_ids"):
        members = [u for u in members if u.id in set(options["diner_ids"]) or u.id == user.id]
    people = int(options.get("people") or parsed.get("people") or len(members) or 1)
    members = members[:max(1, people)]

    diners = []
    for u in members:
        profile = user_profile(u)
        if u.id == user.id:
            for key in ("height_cm", "weight_kg", "goal"):
                if parsed.get(key):
                    profile[key] = parsed[key]
            profile["avoidances"] = list(dict.fromkeys(profile["avoidances"] + parsed.get("avoid", [])))
            profile["allergens"] = list(dict.fromkeys(profile["allergens"] + parsed.get("allergens", [])))
            profile["dietary_groups"] = list(dict.fromkeys(profile["dietary_groups"] + parsed.get("dietary_groups", [])))
        diners.append(make_diner(f"u{u.id}", u.nickname or f"成员{u.id}", profile, wiki, overrides))
    for i in range(people - len(diners)):
        guest = {"goal": parsed.get("goal") or "maintain"}
        diners.append(make_diner(f"g{i + 1}", f"同伴{i + 1}", guest, wiki, overrides, is_guest=True))

    days = int(options.get("days") or parsed.get("days") or 7)
    meals = options.get("meals") or parsed.get("meals") or ["lunch", "dinner"]
    if parsed.get("budget_amount"):
        mode, amount, scale = parsed.get("budget_mode", "per_person"), parsed["budget_amount"], 1.0
    else:
        mode, amount, scale = group.budget_mode, group.budget_amount, days / 7
    total = None
    if amount:
        total = round((amount * len(diners) if mode == "per_person" else amount) * scale, 2)
    budget = {"mode": mode, "amount": amount, "total": total, "people": len(diners),
              "source": "instruction" if parsed.get("budget_amount") else "group_settings"}

    snapshot = _mention_items(parsed.get("inventory_mentions", []), inv_service.snapshot(db, group.id, wiki), wiki)
    ut, gt = twin_service.ensure_fresh(db, user, group, wiki, force=bool(options.get("refresh_twin")))
    twin_service.record(db, user.id, group.id, "diners", {"count": len(diners)})
    db.commit()

    start = date.fromisoformat(options["start_date"]) if options.get("start_date") else date.today()
    return PlanningContext(
        wiki=wiki, llm=llm, instruction=instruction, parsed=parsed, diners=diners, days=days, meals=meals,
        start_date=start, inventory=snapshot, history=price_history(db, group.id, wiki), budget=budget,
        twin=twin_service.planning_view(ut, gt), overrides=overrides, options=options, emit=emit,
    )
