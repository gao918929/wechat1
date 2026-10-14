"""Budget Constraint Agent (priority 4): keep costs under control."""
from __future__ import annotations

from . import composer as C
from . import dishes as D
from .base import Agent, state_from_draft
from .context import PlanningContext


class BudgetAgent(Agent):
    key = "budget"
    title = "预算约束智能体"
    priority = 4
    system_prompt = """你是 MealAgent 的【预算约束智能体】，职责：测算总成本（优先使用用户历史真实成交价，
无历史时使用参考价并标注“估算”），超预算时用同类更实惠的食材/菜替换，且不得违反任何过敏原与禁忌。
成本数字由程序计算，你只负责策略与替换建议，按候选菜名称引用。
输出 JSON：{"summary":"一句话","budget_friendly_dishes":[...],"expensive_to_avoid":[...],"strategy":"..."}"""

    def rules_analyze(self, ctx: PlanningContext) -> dict:
        total = ctx.budget_total()
        slots = ctx.days * len(ctx.meals) * max(1, len(ctx.diners))
        per_meal = round(total / slots, 2) if total else None
        costs = []
        for c in ctx.candidates:
            i = C.info(ctx, c)
            costs.append({"name": c["name"], "kind": c["kind"], "cost": i["cost"]["cost"],
                          "estimated": i["cost"]["estimated"],
                          "protein_per_yuan": round(i["nutrition"]["protein"] / max(0.5, i["cost"]["cost"]), 1)})
        mains = [x for x in costs if x["kind"] in ("main", "one_pot", "breakfast")]
        friendly = [x["name"] for x in sorted(mains, key=lambda x: -x["protein_per_yuan"])[:8]]
        friendly += [x["name"] for x in sorted((x for x in costs if x["kind"] == "veg"), key=lambda x: x["cost"])[:4]]
        expensive = [x["name"] for x in sorted(costs, key=lambda x: -x["cost"])[:5]]
        hist = sum(1 for n in ctx.history)
        if total:
            summary = (f"预算 ¥{total:.0f}（{'人均 ¥%.0f' % ctx.budget['amount'] if ctx.budget.get('mode') == 'per_person' else '总预算'}）"
                       f"，约每人每餐 ¥{per_meal:.1f}；价格来源：历史成交价 {hist} 种，其余为参考价（估算）")
        else:
            summary = "未设置预算，仅测算成本"
        return {"summary": summary, "budget_total": total, "per_person_meal": per_meal, "dish_costs": costs,
                "budget_friendly_dishes": friendly, "expensive_to_avoid": expensive if total else [],
                "strategy": "优先选择高蛋白性价比菜品，合并采购同类食材"}

    def analyze_payload(self, ctx: PlanningContext, base: dict) -> dict:
        return {
            "budget": ctx.budget, "people": len(ctx.diners), "days": ctx.days, "meals": ctx.meals,
            "per_person_meal_budget": base["per_person_meal"], "dish_costs": base["dish_costs"],
            "knowledge": ctx.wiki.context(rules=["budget_calculations"]),
        }

    def merge(self, ctx: PlanningContext, base: dict, resp: dict) -> dict:
        out = dict(base)
        out["summary"] = resp.get("summary") or base["summary"]
        out["budget_friendly_dishes"] = self._known_names(ctx, resp.get("budget_friendly_dishes")) or base["budget_friendly_dishes"]
        out["expensive_to_avoid"] = self._known_names(ctx, resp.get("expensive_to_avoid")) or base["expensive_to_avoid"]
        out["strategy"] = resp.get("strategy") or base["strategy"]
        return out

    def rules_revise(self, ctx: PlanningContext, draft: dict, issues: list[dict], variant: str) -> list[dict]:
        issue = next((i for i in issues if i["kind"] == "over_budget"), None)
        if not issue:
            return []
        target_saving = issue["over"] * 1.15
        state = state_from_draft(ctx, draft)
        due_names = {d["name"] for d in C.inventory_due(ctx)}
        people = max(1, len(ctx.diners))
        occurrences = []
        for d in draft["days"]:
            for m in d["meals"]:
                for x in m["dishes"]:
                    if any(i["name"] in due_names for i in x["ingredients"]):
                        continue  # never trade away the dish that uses near-expiry stock
                    occurrences.append((C.info(ctx, x)["cost"]["cost"] * people, d["day"], m, x))
        occurrences.sort(key=lambda o: -o[0])
        ops, saved = [], 0.0
        for cost, day, m, dish in occurrences:
            if saved >= target_saving:
                break
            names = {x["name"] for x in m["dishes"]}
            pool = [c for c in ctx.candidates if C.slot_fits(c, dish["kind"], m["meal"], variant)
                    and c["name"] not in names and C.info(ctx, c)["cost"]["cost"] * people < cost * 0.8
                    and c["name"] not in state["by_day"].get(day, set())]
            if pool:
                pick = max(pool, key=lambda c: C.score(ctx, c, day, m["meal"], "budget", state))
                ops.append({"op": "replace", "day": day, "meal": m["meal"], "dish": dish["name"], "with": pick["name"]})
                saved += cost - C.info(ctx, pick)["cost"]["cost"] * people
                state["by_day"].setdefault(day, set()).add(pick["name"])
                continue
            sub = self._cheaper_ingredient(ctx, dish)
            if sub:
                new = D.substitute(dish, sub[0], sub[1], ctx.wiki)
                if new:
                    ops.append({"op": "substitute", "dish": dish["name"], "from": sub[0], "to": sub[1], "day": day, "meal": m["meal"]})
                    saved += cost - C.info(ctx, new)["cost"]["cost"] * people
        return ops

    def _cheaper_ingredient(self, ctx: PlanningContext, dish: dict) -> tuple[str, str] | None:
        """Swap the priciest protein for a cheaper one that is allowed for everyone at the table."""
        wiki = ctx.wiki
        priced = []
        for i in dish["ingredients"]:
            ing = wiki.ingredient(i["name"])
            if ing and not ing.is_pantry and "high_protein" in ing.tags:
                priced.append((ing.price_mid or 0, ing))
        if not priced:
            return None
        _, src = max(priced, key=lambda p: p[0])
        options = [x for x in wiki.ingredients.values() if "high_protein" in x.tags and x.name != src.name
                   and (x.price_mid or 999) < (src.price_mid or 0) * 0.7 and x.section in ("meat_eggs", "soy_dairy")]
        for opt in sorted(options, key=lambda x: x.price_mid or 999):
            trial = D.substitute(dish, src.name, opt.name, wiki)
            if trial and not D.matches(trial, ctx.hard_labels, wiki) and not any(
                    ctx.unsuitable_reasons(trial, d) for d in ctx.diners):
                return src.name, opt.name
        return None
