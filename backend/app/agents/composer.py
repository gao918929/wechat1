"""Plan composition, revision ops and finalisation (portions, nutrition, cost, labels).

``draft`` = {"key", "days": [{"day", "date", "meals": [{"meal", "dishes": [dish, ...]}]}]}
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta
from statistics import median

from ..llm import LLMError
from ..services.nutrition import add_nutrition
from ..services.shopping import build_shopping
from . import dishes as D
from .context import PlanningContext

VARIANTS = {
    "health": {"title": "方案A 健康优先", "weights": {"inv": 0.6, "health": 2.0, "cost": 0.3, "twin": 1.0},
               "tradeoff": "严格满足营养与忌口，可能超预算或未用完部分临期食材。"},
    "balanced": {"title": "方案B 平衡（推荐）", "weights": {"inv": 1.0, "health": 1.0, "cost": 1.0, "twin": 1.0},
                 "tradeoff": "尽量兼顾营养、库存、预算与口味，综合最优。"},
    "budget": {"title": "方案C 预算优先", "weights": {"inv": 1.0, "health": 0.6, "cost": 2.5, "twin": 0.8},
               "tradeoff": "严格控制成本，部分营养指标允许小幅波动。"},
}
MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
PORTION_MIN, PORTION_MAX = 0.35, 1.8


# ---------------------------------------------------------------------------- memo helpers
def info(ctx: PlanningContext, dish: dict) -> dict:
    key = json.dumps([dish["name"], dish["ingredients"]], ensure_ascii=False, sort_keys=True)
    memo = ctx.memo.setdefault("dish", {})
    if key not in memo:
        memo[key] = {
            "nutrition": D.per_serving_nutrition(dish, ctx.wiki),
            "cost": D.per_serving_cost(dish, ctx.wiki, ctx.history),
            "labels": D.labels_main(dish, ctx.wiki),
        }
    return memo[key]


def _median_cost(ctx: PlanningContext, kind: str) -> float:
    memo = ctx.memo.setdefault("median_cost", {})
    if kind not in memo:
        costs = [info(ctx, c)["cost"]["cost"] for c in ctx.candidates if c["kind"] == kind] or [5.0]
        memo[kind] = max(1.0, median(costs))
    return memo[kind]


def _jitter(*parts) -> float:
    h = hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:6], 16) / 0xFFFFFF * 0.3


def slot_fits(dish: dict, slot: str, meal: str, variant: str) -> bool:
    if meal not in dish.get("meals", []):
        return False
    kind = dish["kind"]
    if slot == "breakfast":
        return kind in ("breakfast", "main", "staple", "one_pot")
    if slot == "staple":
        return kind == "staple" or (kind == "one_pot" and variant == "budget")
    return kind == slot


def inventory_due(ctx: PlanningContext) -> list[dict]:
    """Near-expiry / not-fresh inventory items and the plan day they must be used by."""
    out = []
    for item in ctx.inventory:
        if item["level"] in ("near_expiry", "not_fresh") and item.get("known", True):
            due = max(1, min(ctx.days, item["days_left"] + 1 if item["level"] == "near_expiry" else 1))
            out.append({"name": item["name"], "due_day": due, "level": item["level"], "grams": item["grams"]})
    return out


# ---------------------------------------------------------------------------- scoring
def score(ctx: PlanningContext, dish: dict, day: int, meal: str, variant: str, state: dict) -> float:
    w = VARIANTS[variant]["weights"]
    i = info(ctx, dish)
    labels = i["labels"]
    s = _jitter(dish["name"], day, meal, variant)

    # inventory priority: reward dishes that use stock, strongly for items due soon
    due = {d["name"]: d["due_day"] for d in inventory_due(ctx)}
    in_stock = {it["name"] for it in ctx.inventory}
    for ing in dish["ingredients"]:
        n = ing["name"]
        if state["inv_left"].get(n, 0) <= 0:
            continue
        if n in due and day <= due[n]:
            s += w["inv"] * 6.0
        elif n in in_stock:
            s += w["inv"] * 1.5
    if dish["name"] in ctx.agent_outputs.get("inventory", {}).get("suggested_dishes", []) and any(
            state["inv_left"].get(ing["name"], 0) > 0 for ing in dish["ingredients"]):
        s += w["inv"] * 1.0

    # health: diet-model tags and agent recommendations
    health = ctx.agent_outputs.get("health", {})
    prefer, avoid = set(health.get("prefer_tags", [])), set(health.get("avoid_tags", []))
    s += w["health"] * (0.8 * len(labels & prefer) - 2.0 * len(labels & avoid))
    if dish["name"] in health.get("recommended_dishes", []):
        s += w["health"] * 2.0
    if dish["name"] in health.get("avoid_dishes", []):
        s -= w["health"] * 3.0
    if dish["kind"] in ("main", "one_pot", "breakfast"):
        s += w["health"] * i["nutrition"]["protein"] / 12.0

    # iterative optimisation: digital-twin preferences
    it = ctx.agent_outputs.get("iterative", {})
    learned = it.get("dish_scores", {}).get(dish["name"], 0.0)
    s += w["twin"] * 0.9 * max(-5.0, min(5.0, learned))
    if dish["name"] in it.get("favor_dishes", []):
        s += w["twin"] * 1.0
    if dish["name"] in it.get("avoid_dishes", []):
        s -= w["twin"] * 3.0
    s += w["twin"] * 0.5 * sum(1 for ing in dish["ingredients"] if ing["name"] in it.get("favor_ingredients", []))
    s -= w["twin"] * 1.5 * sum(1 for ing in dish["ingredients"] if ing["name"] in it.get("avoid_ingredients", []))

    # budget
    b = ctx.agent_outputs.get("budget", {})
    s -= w["cost"] * 1.5 * i["cost"]["cost"] / _median_cost(ctx, dish["kind"])
    if dish["name"] in b.get("budget_friendly_dishes", []):
        s += w["cost"] * 1.0
    if dish["name"] in b.get("expensive_to_avoid", []):
        s -= w["cost"] * 1.0

    # variety
    s -= 3.0 * state["counts"].get(dish["name"], 0)
    if dish["name"] in state["by_day"].get(day - 1, set()):
        s -= 3.0
    if dish["name"] in it.get("recent_dishes", []):
        s -= 0.5
    # differentiated mode: dishes more people can share are preferred
    if ctx.differentiated:
        s += 0.8 * len(ctx.suitability(dish)["suitable_for"])
    return s


def _new_state(ctx: PlanningContext) -> dict:
    return {"counts": {}, "by_day": {}, "inv_left": {it["name"]: it["grams"] or 300.0 for it in ctx.inventory}}


def _take(ctx: PlanningContext, state: dict, dish: dict, day: int) -> None:
    state["counts"][dish["name"]] = state["counts"].get(dish["name"], 0) + 1
    state["by_day"].setdefault(day, set()).add(dish["name"])
    for ing in dish["ingredients"]:
        if ing["name"] in state["inv_left"]:
            state["inv_left"][ing["name"]] -= ing["grams"] * len(ctx.diners)


def best_for_slot(ctx, slot, meal, day, variant, state, exclude=(), diner=None) -> dict | None:
    pool = [c for c in ctx.candidates if slot_fits(c, slot, meal, variant) and c["name"] not in exclude
            and c["name"] not in state["by_day"].get(day, set())]
    if diner is not None:
        pool = [c for c in pool if not ctx.unsuitable_reasons(c, diner)]
    if not pool:
        return None
    return copy.deepcopy(max(pool, key=lambda c: score(ctx, c, day, meal, variant, state)))


def _apply_substitution_rules(ctx: PlanningContext, dish: dict) -> dict:
    """Iterative agent: learned "replaced X with Y" habits, if Y is allowed for everyone."""
    for rule in ctx.agent_outputs.get("iterative", {}).get("substitutions", []):
        new = D.substitute(dish, rule["from"], rule["to"], ctx.wiki)
        if new and not D.matches(new, ctx.hard_labels, ctx.wiki) and not any(
                ctx.unsuitable_reasons(new, d) for d in ctx.diners if not ctx.differentiated):
            dish = new
    return dish


def ensure_coverage(ctx: PlanningContext, meal_obj: dict, day: int, variant: str, state: dict) -> None:
    """Differentiated mode: each diner gets at least one suitable protein dish per meal."""
    if not ctx.differentiated:
        return
    for d in ctx.diners:
        ok = any(not ctx.unsuitable_reasons(x, d) for x in meal_obj["dishes"]
                 if x["kind"] in ("main", "one_pot", "breakfast"))
        if ok:
            continue
        slot = "breakfast" if meal_obj["meal"] == "breakfast" else "main"
        pick = best_for_slot(ctx, slot, meal_obj["meal"], day, variant, state,
                             exclude={x["name"] for x in meal_obj["dishes"]}, diner=d)
        if pick:
            pick["for_diner"] = d.id
            meal_obj["dishes"].append(pick)
            _take(ctx, state, pick, day)


def compose_rules(ctx: PlanningContext, variant: str) -> dict:
    state = _new_state(ctx)
    days = []
    for day in range(1, ctx.days + 1):
        meals = []
        for meal in ctx.meals:
            chosen: list[dict] = []
            for slot in ctx.meal_slots(meal):
                pick = best_for_slot(ctx, slot, meal, day, variant, state, exclude={c["name"] for c in chosen})
                if pick:
                    pick = _apply_substitution_rules(ctx, pick)
                    chosen.append(pick)
                    _take(ctx, state, pick, day)
            meal_obj = {"meal": meal, "dishes": chosen}
            ensure_coverage(ctx, meal_obj, day, variant, state)
            meals.append(meal_obj)
        days.append({"day": day, "date": (ctx.start_date + timedelta(days=day - 1)).isoformat(), "meals": meals})
    return {"key": variant, "days": days, "composer": "rules"}


COMPOSE_PROMPT = """你是 MealAgent 的中央调度器（Task Orchestrator）。四个独立智能体（健康适配、库存优先、预算约束、迭代优化）
已分别给出分析结果。请据此为用户编排一周菜单。

规则：
1. 优先级：特殊人群营养需求 > 过敏原 > 口味忌口 > 库存优先 > 预算。
2. 菜品优先从“候选菜”中按名称选择；确需新菜时可给出对象 {"name","kind","ingredients":[{"name","grams"}]}，
   食材名必须来自知识库，grams 为每人份克数。
3. 每餐按 slots 给出的结构选菜（main 荤/蛋白主菜, veg 素菜, soup 汤, staple 主食, breakfast 早餐）。
4. 临期食材必须在 use_by_day 之前用掉；同一道菜一周内尽量不超过 2 次，相邻两天不重复。
5. 方案策略：{strategy}

输出 JSON：{"days":[{"day":1,"meals":[{"meal":"dinner","dishes":["菜名", ...]}]}],"notes":"一句话说明取舍"}"""


async def compose_llm(ctx: PlanningContext, variant: str) -> dict:
    """The orchestrator's own LLM call that composes a variant from the agents' outputs."""
    payload = {
        "variant": variant, "days": ctx.days, "meals": ctx.meals,
        "slots": {m: ctx.meal_slots(m) for m in ctx.meals},
        "diners": [{"name": d.name, "special": d.special, "avoid": sorted(d.avoid),
                    "meal_targets": {m: d.meal_target(m, ctx.wiki) for m in ctx.meals}} for d in ctx.diners],
        "differentiated": ctx.differentiated,
        "agents": {k: {kk: vv for kk, vv in v.items() if kk not in ("seconds",)} for k, v in ctx.agent_outputs.items()},
        "candidates": [D.brief(c, ctx.wiki, ctx.history) for c in ctx.candidates],
    }
    system = COMPOSE_PROMPT.replace("{strategy}", VARIANTS[variant]["title"] + "：" + VARIANTS[variant]["tradeoff"])
    resp = await ctx.llm.chat_json(system, payload, agent="orchestrator")
    by_name = {c["name"]: c for c in ctx.candidates}
    state = _new_state(ctx)
    days = []
    for day in range(1, ctx.days + 1):
        src_day = next((d for d in resp.get("days", []) if int(d.get("day", 0)) == day), {"meals": []})
        meals = []
        for meal in ctx.meals:
            src_meal = next((m for m in src_day.get("meals", []) if m.get("meal") == meal), {"dishes": []})
            chosen = []
            for item in src_meal.get("dishes", []):
                if isinstance(item, str) and item in by_name:
                    dish = copy.deepcopy(by_name[item])
                elif isinstance(item, dict) and item.get("ingredients"):
                    dish = D.normalize_custom(item, ctx.wiki)
                elif isinstance(item, dict) and item.get("name") in by_name:
                    dish = copy.deepcopy(by_name[item["name"]])
                else:
                    continue
                if dish["name"] not in {c["name"] for c in chosen}:
                    chosen.append(dish)
                    _take(ctx, state, dish, day)
            meal_obj = {"meal": meal, "dishes": chosen}
            ensure_coverage(ctx, meal_obj, day, variant, state)
            meals.append(meal_obj)
        days.append({"day": day, "date": (ctx.start_date + timedelta(days=day - 1)).isoformat(), "meals": meals})
    return {"key": variant, "days": days, "composer": "llm", "notes": resp.get("notes", "")}


async def compose(ctx: PlanningContext, variant: str) -> dict:
    if ctx.llm.online:
        try:
            draft = await compose_llm(ctx, variant)
            if sum(len(m["dishes"]) for d in draft["days"] for m in d["meals"]):
                return draft
            ctx.warnings.append("调度器 LLM 输出为空，已改用规则编排。")
        except LLMError as exc:
            ctx.warnings.append(f"调度器 LLM 调用失败（{str(exc)[:60]}），已改用规则编排。")
    return compose_rules(ctx, variant)


# ---------------------------------------------------------------------------- ops
def _find_meal(draft: dict, day: int, meal: str) -> dict | None:
    for d in draft["days"]:
        if d["day"] == day:
            return next((m for m in d["meals"] if m["meal"] == meal), None)
    return None


def resolve_dish(ctx: PlanningContext, ref) -> dict | None:
    if isinstance(ref, dict) and ref.get("ingredients"):
        return D.normalize_custom(ref, ctx.wiki)
    name = ref.get("name") if isinstance(ref, dict) else ref
    c = ctx.candidate(name) if name else None
    return copy.deepcopy(c) if c else None


def apply_ops(ctx: PlanningContext, draft: dict, ops: list[dict]) -> list[str]:
    applied = []
    for op in ops:
        kind = op.get("op")
        if kind == "substitute":
            for d in draft["days"]:
                for m in d["meals"]:
                    for idx, dish in enumerate(m["dishes"]):
                        if op.get("dish") in (None, "*", dish["name"]) and (
                                op.get("day") in (None, d["day"])) and (op.get("meal") in (None, m["meal"])):
                            new = D.substitute(dish, op.get("from", ""), op.get("to", ""), ctx.wiki)
                            if new:
                                new["for_diner"] = dish.get("for_diner")
                                m["dishes"][idx] = new
                                applied.append(f"第{d['day']}天{MEAL_LABELS.get(m['meal'], m['meal'])}：{dish['name']} 中 {op['from']}→{op['to']}")
            continue
        meal_obj = _find_meal(draft, int(op.get("day", 0) or 0), op.get("meal", ""))
        if meal_obj is None:
            continue
        where = f"第{op['day']}天{MEAL_LABELS.get(op['meal'], op['meal'])}"
        names = [x["name"] for x in meal_obj["dishes"]]
        if kind == "replace" and op.get("dish") in names:
            new = resolve_dish(ctx, op.get("with"))
            if new and new["name"] not in names:
                idx = names.index(op["dish"])
                new["for_diner"] = meal_obj["dishes"][idx].get("for_diner")
                meal_obj["dishes"][idx] = new
                applied.append(f"{where}：{op['dish']} → {new['name']}")
        elif kind == "add":
            new = resolve_dish(ctx, op.get("dish"))
            if new and new["name"] not in names:
                if op.get("for_diner"):
                    new["for_diner"] = op["for_diner"]
                meal_obj["dishes"].append(new)
                applied.append(f"{where}：新增 {new['name']}")
        elif kind == "remove" and op.get("dish") in names and len(names) > 1:
            meal_obj["dishes"].pop(names.index(op["dish"]))
            applied.append(f"{where}：移除 {op['dish']}")
    return applied


# ---------------------------------------------------------------------------- finalise
def finalize(ctx: PlanningContext, draft: dict) -> dict:
    """Compute portions per diner, nutrition, labels, inventory usage, cost and shopping list."""
    wiki = ctx.wiki
    need: dict[str, float] = {}
    inv_names = {it["name"] for it in ctx.inventory}
    due = {d["name"]: d for d in inventory_due(ctx)}
    used_due: dict[str, int] = {}
    out_days = []
    for d in draft["days"]:
        out_meals = []
        for m in d["meals"]:
            dishes_out = []
            eaters: dict[int, list[str]] = {}
            for idx, dish in enumerate(m["dishes"]):
                suit = ctx.suitability(dish) if ctx.differentiated else {"suitable_for": [x.id for x in ctx.diners], "not_for": []}
                if dish.get("for_diner") and dish["for_diner"] not in suit["suitable_for"]:
                    suit["suitable_for"].append(dish["for_diner"])
                eaters[idx] = suit["suitable_for"]
                dishes_out.append((dish, suit))
            per_diner = {}
            for diner in ctx.diners:
                target = diner.meal_target(m["meal"], wiki)
                base = {"kcal": 0.0}
                for idx, (dish, _) in enumerate(dishes_out):
                    if diner.id in eaters[idx]:
                        base = add_nutrition(base, info(ctx, dish)["nutrition"])
                raw = target["kcal"] / base["kcal"] if base.get("kcal") else 1.0
                factor = max(PORTION_MIN, min(PORTION_MAX, raw))
                intake = {k: round(v * factor, 1) for k, v in base.items() if isinstance(v, (int, float))}
                per_diner[diner.id] = {"factor": round(factor, 2), "clamped": raw != factor, "target": target,
                                       "intake": intake}
            meal_cost = 0.0
            dish_rows = []
            for idx, (dish, suit) in enumerate(dishes_out):
                i = info(ctx, dish)
                portions = {did: per_diner[did]["factor"] for did in eaters[idx]}
                servings = round(sum(portions.values()), 2)
                for ing in dish["ingredients"]:
                    need[ing["name"]] = need.get(ing["name"], 0.0) + ing["grams"] * servings
                    if ing["name"] in due and ing["name"] not in used_due:
                        used_due[ing["name"]] = d["day"]
                cost = round(i["cost"]["cost"] * servings, 2)
                meal_cost += cost
                row = {
                    "name": dish["name"], "en": dish.get("en", ""), "kind": dish["kind"], "spicy": dish.get("spicy", 0),
                    "minutes": dish.get("minutes"), "steps": dish.get("steps", ""), "source": dish.get("source", ""),
                    "ingredients": dish["ingredients"], "servings": servings, "portions": portions,
                    "nutrition_per_serving": {k: i["nutrition"][k] for k in ("kcal", "protein", "fat", "carb")},
                    "cost_per_serving": i["cost"]["cost"], "cost_estimated": i["cost"]["estimated"], "cost": cost,
                    "uses_inventory": [x["name"] for x in dish["ingredients"] if x["name"] in inv_names],
                    "notes": dish.get("notes", []), "for_diner": dish.get("for_diner"),
                }
                if ctx.differentiated:
                    names = {x.id: x.name for x in ctx.diners}
                    row["suitable_for"] = [names[x] for x in eaters[idx]]
                    row["not_for"] = suit["not_for"]
                    label = "适合：" + ("全员" if len(eaters[idx]) == len(ctx.diners) else "、".join(row["suitable_for"]))
                    if suit["not_for"]:
                        label += "；" + "；".join(f"{n['name']}{n['reasons'][0]}" for n in suit["not_for"])
                    if dish.get("for_diner"):
                        label = f"{names.get(dish['for_diner'], '')}专属 · " + label
                    row["label"] = label
                dish_rows.append(row)
            out_meals.append({"meal": m["meal"], "meal_label": MEAL_LABELS.get(m["meal"], m["meal"]),
                              "dishes": dish_rows, "diners": per_diner, "cost": round(meal_cost, 2)})
        out_days.append({"day": d["day"], "date": d["date"], "meals": out_meals})

    shopping = build_shopping(need, ctx.inventory, ctx.history, wiki, people=len(ctx.diners),
                              budget_total=ctx.budget_total())
    unused_due = [{"name": n, "due_day": x["due_day"]} for n, x in due.items() if n not in used_due]
    late_due = [{"name": n, "due_day": x["due_day"], "used_day": used_due[n]} for n, x in due.items()
                if n in used_due and used_due[n] > x["due_day"]]
    budget_total = ctx.budget_total()
    summary = {
        "total_cost": shopping["total_cost"], "per_person_cost": shopping["per_person_cost"],
        "budget_total": budget_total, "budget_mode": ctx.budget.get("mode"), "budget_amount": ctx.budget.get("amount"),
        "within_budget": None if not budget_total else shopping["total_cost"] <= budget_total,
        "budget_utilization": round(shopping["total_cost"] / budget_total, 2) if budget_total else None,
        "near_expiry_used": [{"name": n, "day": day} for n, day in used_due.items()],
        "near_expiry_unused": unused_due, "near_expiry_late": late_due,
        "cost_estimated": shopping["estimated"],
    }
    return {"key": draft["key"], "title": VARIANTS[draft["key"]]["title"], "tradeoff": VARIANTS[draft["key"]]["tradeoff"],
            "composer": draft.get("composer"), "composer_notes": draft.get("notes", ""), "days": out_days,
            "summary": summary, "shopping": shopping, "differentiated": ctx.differentiated,
            "label": "智能体建议，可自由调整"}
