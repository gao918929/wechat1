"""Inventory Priority Agent (priority 3): minimise waste by scheduling stock, near-expiry first."""
from __future__ import annotations

from . import composer as C
from .base import Agent, meal_of, state_from_draft
from .context import PlanningContext


class InventoryAgent(Agent):
    key = "inventory"
    title = "库存优先智能体"
    priority = 3
    system_prompt = """你是 MealAgent 的【库存优先智能体】，职责：识别临期与在库食材，要求方案优先使用它们，
目标是减少浪费。临期/外观不新鲜的食材必须在 use_by_day 之前安排进菜单；保质期数据由程序计算，不得修改。
只能从候选菜中选择消耗这些食材的菜，按名称引用。
输出 JSON：{"summary":"一句话","schedule":[{"name":"食材","use_by_day":1,"suggested_dishes":["菜名"]}],
"suggested_dishes":["整体优先安排的菜名"]}"""

    def rules_analyze(self, ctx: PlanningContext) -> dict:
        due = {d["name"]: d for d in C.inventory_due(ctx)}
        priorities = []
        for item in ctx.inventory:
            uses = [c["name"] for c in ctx.candidates if any(i["name"] == item["name"] for i in c["ingredients"])]
            d = due.get(item["name"])
            priorities.append({
                "name": item["name"], "grams": round(item["grams"] or 0), "estimated": item.get("estimated", False),
                "days_left": item["days_left"], "level": item["level"], "urgent": d is not None,
                "use_by_day": d["due_day"] if d else ctx.days, "dishes": uses[:6],
            })
        priorities.sort(key=lambda p: (not p["urgent"], p["use_by_day"], p["days_left"]))
        urgent = [p for p in priorities if p["urgent"]]
        no_dish = [p["name"] for p in urgent if not p["dishes"]]
        summary = ("临期优先：" + "、".join(f"{p['name']}（第{p['use_by_day']}天前）" for p in urgent)) if urgent else (
            f"库存 {len(priorities)} 种食材，无临期" if priorities else "库存为空，全部需采购")
        if no_dish:
            summary += f"；{'、'.join(no_dish)} 没有可用菜谱（违反忌口或无匹配）"
        suggested = list(dict.fromkeys(n for p in urgent for n in p["dishes"][:3]))
        return {"summary": summary, "priorities": priorities, "suggested_dishes": suggested, "unusable": no_dish}

    def analyze_payload(self, ctx: PlanningContext, base: dict) -> dict:
        return {
            "days": ctx.days, "meals": ctx.meals, "inventory": base["priorities"],
            "knowledge": ctx.wiki.context(rules=["shelf_life"]),
            "candidates": [{"name": c["name"], "kind": c["kind"],
                            "main_ingredients": [i["name"] for i in c["ingredients"]]} for c in ctx.candidates],
        }

    def merge(self, ctx: PlanningContext, base: dict, resp: dict) -> dict:
        out = dict(base)
        out["summary"] = resp.get("summary") or base["summary"]
        by_name = {p["name"]: p for p in out["priorities"]}
        for s in resp.get("schedule") or []:
            p = by_name.get(s.get("name"))
            if p:
                # the LLM may schedule earlier, never later than the computed deadline
                if isinstance(s.get("use_by_day"), int):
                    p["use_by_day"] = min(p["use_by_day"], max(1, s["use_by_day"]))
                p["dishes"] = self._known_names(ctx, s.get("suggested_dishes")) or p["dishes"]
        out["suggested_dishes"] = list(dict.fromkeys(base["suggested_dishes"] + self._known_names(ctx, resp.get("suggested_dishes"))))
        return out

    def rules_revise(self, ctx: PlanningContext, draft: dict, issues: list[dict], variant: str) -> list[dict]:
        ops = []
        state = state_from_draft(ctx, draft)
        due_names = {d["name"] for d in C.inventory_due(ctx)}
        for issue in issues:
            if issue["kind"] == "unknown_ingredient":
                canon = ctx.wiki.resolve(issue["ingredient"])
                if canon:
                    ops.append({"op": "substitute", "dish": issue["dish"], "from": issue["ingredient"], "to": canon,
                                "day": issue["day"], "meal": issue["meal"]})
                    continue
                m = meal_of(draft, issue["day"], issue["meal"])
                bad = next((x for x in m["dishes"] if x["name"] == issue["dish"]), None) if m else None
                if bad:
                    pick = C.best_for_slot(ctx, bad["kind"], issue["meal"], issue["day"], variant, state,
                                           exclude={x["name"] for x in m["dishes"]})
                    ops.append({"op": "replace", "day": issue["day"], "meal": issue["meal"], "dish": bad["name"],
                                "with": pick["name"]} if pick else
                               {"op": "remove", "day": issue["day"], "meal": issue["meal"], "dish": bad["name"]})
            elif issue["kind"] == "near_expiry_unused":
                name, due_day = issue["name"], issue["due_day"]
                users = [c for c in ctx.candidates if any(i["name"] == name for i in c["ingredients"])]
                placed = False
                for day in range(1, due_day + 1):
                    for m in next(d for d in draft["days"] if d["day"] == day)["meals"]:
                        names = {x["name"] for x in m["dishes"]}
                        fits = [c for c in users if m["meal"] in c["meals"] and c["name"] not in names]
                        if not fits:
                            continue
                        pick = max(fits, key=lambda c: C.score(ctx, c, day, m["meal"], variant, state))
                        target = next((x for x in m["dishes"] if x["kind"] == pick["kind"] and not any(
                            i["name"] in due_names for i in x["ingredients"])), None)
                        if target:
                            ops.append({"op": "replace", "day": day, "meal": m["meal"], "dish": target["name"], "with": pick["name"]})
                        else:
                            ops.append({"op": "add", "day": day, "meal": m["meal"], "dish": pick["name"]})
                        placed = True
                        break
                    if placed:
                        break
        return ops
