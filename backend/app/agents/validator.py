"""Three-layer validator (inventory → nutrition → budget) plus the hard-constraint veto check.

Each issue names the agent responsible for fixing it, so the orchestrator can route it back for
regeneration (up to ``settings.max_validation_retries`` times).
"""
from __future__ import annotations

from . import dishes as D
from .composer import MEAL_LABELS
from .context import PlanningContext, label_text

KCAL_LOW, KCAL_HIGH, PROTEIN_MIN = 0.8, 1.25, 0.8


def validate(ctx: PlanningContext, variant: dict) -> dict:
    wiki = ctx.wiki
    issues: list[dict] = []

    def add(layer: str, agent: str, kind: str, message: str, **detail) -> None:
        issues.append({"layer": layer, "agent": agent, "kind": kind, "message": message, **detail})

    # ---- hard constraints (absolute veto) + soft constraints in everyone-compatible mode
    for d in variant["days"]:
        for m in d["meals"]:
            where = f"第{d['day']}天{MEAL_LABELS[m['meal']]}"
            for dish in m["dishes"]:
                hard = D.matches(dish, ctx.hard_labels, wiki, "all")
                if hard:
                    add("hard", "health", "hard_violation", f"{where}「{dish['name']}」含禁忌：{'、'.join(map(label_text, hard))}",
                        day=d["day"], meal=m["meal"], dish=dish["name"])
                elif not ctx.differentiated:
                    for diner in ctx.diners:
                        r = ctx.unsuitable_reasons(dish, diner)
                        if r:
                            add("hard", "health", "soft_violation", f"{where}「{dish['name']}」：{diner.name}{r[0]}",
                                day=d["day"], meal=m["meal"], dish=dish["name"])
                            break

    # ---- layer 1: inventory (ingredients available in stock or purchasable; near-expiry used in time)
    for d in variant["days"]:
        for m in d["meals"]:
            for dish in m["dishes"]:
                for ing in dish["ingredients"]:
                    if wiki.ingredient(ing["name"]) is None:
                        add("inventory", "inventory", "unknown_ingredient",
                            f"「{dish['name']}」中的“{ing['name']}”不在知识库，无法确认可购买",
                            day=d["day"], meal=m["meal"], dish=dish["name"], ingredient=ing["name"])
    for u in variant["summary"]["near_expiry_unused"]:
        add("inventory", "inventory", "near_expiry_unused", f"临期食材“{u['name']}”未安排在第{u['due_day']}天前使用",
            name=u["name"], due_day=u["due_day"])
    for u in variant["summary"]["near_expiry_late"]:
        add("inventory", "inventory", "near_expiry_unused",
            f"临期食材“{u['name']}”安排在第{u['used_day']}天，晚于第{u['due_day']}天", name=u["name"], due_day=u["due_day"])

    # ---- layer 2: nutrition (per diner per meal)
    names = {x.id: x.name for x in ctx.diners}
    for d in variant["days"]:
        for m in d["meals"]:
            where = f"第{d['day']}天{MEAL_LABELS[m['meal']]}"
            non_staple = [x for x in m["dishes"] if x["kind"] != "staple"]
            if len(m["dishes"]) < 2 or not non_staple:
                add("nutrition", "health", "few_dishes", f"{where}菜品过少", day=d["day"], meal=m["meal"])
                continue
            for did, nd in m["diners"].items():
                t, got = nd["target"], nd["intake"]
                if got.get("kcal", 0) < t["kcal"] * KCAL_LOW:
                    add("nutrition", "health", "kcal_low", f"{where}{names[did]}能量 {got.get('kcal', 0):.0f}/{t['kcal']} kcal 偏低",
                        day=d["day"], meal=m["meal"], diner=did)
                elif got.get("kcal", 0) > t["kcal"] * KCAL_HIGH:
                    add("nutrition", "health", "kcal_high", f"{where}{names[did]}能量 {got.get('kcal', 0):.0f}/{t['kcal']} kcal 偏高",
                        day=d["day"], meal=m["meal"], diner=did)
                if got.get("protein", 0) < t["protein_g"] * PROTEIN_MIN:
                    add("nutrition", "health", "protein_low",
                        f"{where}{names[did]}蛋白质 {got.get('protein', 0):.0f}/{t['protein_g']:.0f} g 不足",
                        day=d["day"], meal=m["meal"], diner=did)
            if ctx.differentiated:
                for diner in ctx.diners:
                    ok = any(diner.name in x.get("suitable_for", []) for x in m["dishes"]
                             if x["kind"] in ("main", "one_pot", "breakfast"))
                    if not ok:
                        add("nutrition", "health", "no_suitable_dish", f"{where}没有适合{diner.name}的主菜",
                            day=d["day"], meal=m["meal"], diner=diner.id)

    # ---- layer 3: budget
    s = variant["summary"]
    if s["budget_total"] and s["total_cost"] > s["budget_total"]:
        add("budget", "budget", "over_budget",
            f"预计采购 ¥{s['total_cost']:.2f} 超出预算 ¥{s['budget_total']:.0f}（超 ¥{s['total_cost'] - s['budget_total']:.2f}）",
            over=round(s["total_cost"] - s["budget_total"], 2))

    layers = {}
    for layer in ("hard", "inventory", "nutrition", "budget"):
        li = [i for i in issues if i["layer"] == layer]
        layers[layer] = {"passed": not li, "issues": len(li)}
    return {"passed": not issues, "layers": layers, "issues": issues}


def suggestions(ctx: PlanningContext, variant: dict, report: dict) -> dict:
    """When validation still fails after retries: what to relax, and what is already satisfied."""
    tips, satisfied = [], []
    layers = report["layers"]
    if not layers["budget"]["passed"]:
        need = variant["summary"]["total_cost"]
        tips.append(f"提高预算至约 ¥{need:.0f}（人均 ¥{need / max(1, len(ctx.diners)):.0f}），或接受方案C 预算优先")
    if not layers["inventory"]["passed"]:
        tips.append("补充可替代的库存食材，或接受部分临期食材未用完（建议尽快单独处理）")
    if not layers["nutrition"]["passed"]:
        tips.append("减少部分口味忌口（软约束）以扩大可选菜品，或调整就餐人数/份量")
    if not layers["hard"]["passed"]:
        tips.append("请检查过敏原与禁忌设置是否过严，或补充更多菜谱")
    names = {"hard": "过敏原/禁忌（硬约束）", "inventory": "库存与临期食材", "nutrition": "营养目标", "budget": "预算"}
    for k, v in layers.items():
        if v["passed"]:
            satisfied.append(names[k])
    return {"tips": tips, "satisfied": satisfied}
