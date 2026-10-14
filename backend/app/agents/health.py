"""Health Adaptation Agent (priority 1): nutrition & safety compliance."""
from __future__ import annotations

from ..services.nutrition import DISCLAIMER
from . import composer as C
from .base import Agent, meal_of, state_from_draft
from .context import PlanningContext


class HealthAgent(Agent):
    key = "health"
    title = "健康适配智能体"
    priority = 1
    system_prompt = """你是 MealAgent 的【健康适配智能体】，职责：依据人群膳食模型与健康指标，
校验营养配比、过滤禁忌食材，保证营养与安全合规（优先级最高）。
- 能量与三大营养素目标已由程序依据 DRIs 计算，你不得修改数值，只做解读与选菜建议。
- 过敏原与慢病禁忌是硬约束，绝不推荐含有它们的菜；口味忌口是软约束。
- 只能从候选菜中推荐，按名称引用。
输出 JSON：{"summary":"一句话总结","recommended_dishes":[...],"avoid_dishes":[...],
"prefer_tags":[...],"avoid_tags":[...],"limit_ingredients":[...],"notes":["..."]}"""

    def rules_analyze(self, ctx: PlanningContext) -> dict:
        wiki = ctx.wiki
        prefer, avoid = set(), set()
        for d in ctx.diners:
            for mid in d.models:
                prefer |= wiki.diet_models[mid].tags("prefer_tags")
                avoid |= wiki.diet_models[mid].tags("avoid_tags")
        prefer.discard("-")
        avoid.discard("-")

        def fit(c: dict) -> float:
            labels = C.info(ctx, c)["labels"]
            return len(labels & prefer) - 2 * len(labels & avoid) + C.info(ctx, c)["nutrition"]["protein"] / 10

        mains = [c for c in ctx.candidates if c["kind"] in ("main", "one_pot", "breakfast")]
        recommended = [c["name"] for c in sorted(mains, key=fit, reverse=True)[:8]]
        avoid_dishes = [c["name"] for c in ctx.candidates if C.info(ctx, c)["labels"] & avoid][:10]
        notes = []
        for d in ctx.diners:
            notes += [f"{d.name}：{n}" for n in d.daily.get("notes", [])]
        targets = {d.id: {"name": d.name, "daily": {k: d.daily[k] for k in ("kcal", "protein_g", "fat_g", "carb_g")},
                          "basis": d.daily["basis"], "estimated": d.daily["estimated"],
                          "meals": {m: d.meal_target(m, wiki) for m in ctx.meals}} for d in ctx.diners}
        first = ctx.diners[0]
        summary = (f"{len(ctx.diners)} 位就餐者；{first.name}每日 {first.daily['kcal']} kcal、蛋白质 {first.daily['protein_g']} g"
                   + (f"；差异化多菜：{ctx.diff_reasons[0]}" if ctx.differentiated else "；全员兼容方案"))
        return {"summary": summary, "targets": targets, "prefer_tags": sorted(prefer), "avoid_tags": sorted(avoid),
                "recommended_dishes": recommended, "avoid_dishes": avoid_dishes, "limit_ingredients": [],
                "hard_labels": sorted(ctx.hard_labels), "excluded": ctx.excluded[:30], "notes": notes,
                "differentiated": ctx.differentiated, "diff_reasons": ctx.diff_reasons, "disclaimer": DISCLAIMER}

    def analyze_payload(self, ctx: PlanningContext, base: dict) -> dict:
        model_ids = sorted({m for d in ctx.diners for m in d.models})
        return {
            "diners": [{"name": d.name, "models": d.models, "special": d.special, "allergens": sorted(d.allergens),
                        "avoid": sorted(d.avoid), "targets": base["targets"][d.id]} for d in ctx.diners],
            "hard_labels": base["hard_labels"], "differentiated": ctx.differentiated,
            "knowledge": ctx.wiki.context(diet_ids=model_ids, rules=["nutrition_targets", "conflict_priorities"]),
            "candidates": [C.D.brief(c, ctx.wiki, ctx.history) for c in ctx.candidates],
        }

    def merge(self, ctx: PlanningContext, base: dict, resp: dict) -> dict:
        out = dict(base)
        out["summary"] = resp.get("summary") or base["summary"]
        out["recommended_dishes"] = self._known_names(ctx, resp.get("recommended_dishes")) or base["recommended_dishes"]
        out["avoid_dishes"] = list(dict.fromkeys(base["avoid_dishes"] + self._known_names(ctx, resp.get("avoid_dishes"))))
        out["prefer_tags"] = sorted(set(base["prefer_tags"]) | set(resp.get("prefer_tags") or []))
        out["avoid_tags"] = sorted(set(base["avoid_tags"]) | set(resp.get("avoid_tags") or []))
        out["limit_ingredients"] = [x for x in resp.get("limit_ingredients") or [] if isinstance(x, str)]
        out["notes"] = base["notes"] + [n for n in resp.get("notes") or [] if isinstance(n, str)]
        return out

    def rules_revise(self, ctx: PlanningContext, draft: dict, issues: list[dict], variant: str) -> list[dict]:
        ops, seen = [], set()
        state = state_from_draft(ctx, draft)
        for issue in issues:
            day, meal = issue.get("day"), issue.get("meal")
            m = meal_of(draft, day, meal) if day else None
            if m is None:
                continue
            names = {x["name"] for x in m["dishes"]}
            key = (day, meal, issue["kind"], issue.get("dish"))
            if key in seen:
                continue
            seen.add(key)
            slot_main = "breakfast" if meal == "breakfast" else "main"
            if issue["kind"] in ("hard_violation", "soft_violation"):
                bad = next((x for x in m["dishes"] if x["name"] == issue["dish"]), None)
                slot = bad["kind"] if bad and bad["kind"] in ("main", "veg", "soup", "staple", "breakfast") else slot_main
                pick = C.best_for_slot(ctx, slot, meal, day, variant, state, exclude=names)
                ops.append({"op": "replace", "day": day, "meal": meal, "dish": issue["dish"], "with": pick["name"]}
                           if pick else {"op": "remove", "day": day, "meal": meal, "dish": issue["dish"]})
            elif issue["kind"] == "protein_low":
                if (day, meal, "protein") in seen:
                    continue
                seen.add((day, meal, "protein"))
                pool = [c for c in ctx.candidates if C.slot_fits(c, slot_main, meal, variant) and c["name"] not in names
                        and c["name"] not in state["by_day"].get(day, set())]
                if not pool:
                    continue
                best = max(pool, key=lambda c: (C.info(ctx, c)["nutrition"]["protein"], C.score(ctx, c, day, meal, variant, state)))
                weakest = min((x for x in m["dishes"] if x["kind"] in ("main", "veg", "breakfast")),
                              key=lambda x: C.info(ctx, x)["nutrition"]["protein"], default=None)
                full = len(m["dishes"]) >= len(ctx.meal_slots(meal))
                if weakest and C.info(ctx, weakest)["nutrition"]["protein"] < C.info(ctx, best)["nutrition"]["protein"] and (
                        full or weakest["kind"] != "veg" or sum(1 for x in m["dishes"] if x["kind"] == "veg") > 1):
                    ops.append({"op": "replace", "day": day, "meal": meal, "dish": weakest["name"], "with": best["name"]})
                else:
                    ops.append({"op": "add", "day": day, "meal": meal, "dish": best["name"]})
                state["by_day"].setdefault(day, set()).add(best["name"])
            elif issue["kind"] in ("kcal_low", "few_dishes"):
                if (day, meal, "more") in seen:
                    continue
                seen.add((day, meal, "more"))
                has_staple = any(x["kind"] in ("staple", "one_pot") for x in m["dishes"])
                slot = slot_main if has_staple or meal == "breakfast" else "staple"
                pick = C.best_for_slot(ctx, slot, meal, day, variant, state, exclude=names)
                if pick:
                    ops.append({"op": "add", "day": day, "meal": meal, "dish": pick["name"]})
                    state["by_day"].setdefault(day, set()).add(pick["name"])
            elif issue["kind"] == "kcal_high":
                if (day, meal, "less") in seen:
                    continue
                seen.add((day, meal, "less"))
                heavy = max((x for x in m["dishes"] if x["kind"] not in ("staple", "one_pot")),
                            key=lambda x: C.info(ctx, x)["nutrition"]["kcal"], default=None)
                if heavy is None:
                    continue
                pool = [c for c in ctx.candidates if C.slot_fits(c, heavy["kind"], meal, variant) and c["name"] not in names
                        and C.info(ctx, c)["nutrition"]["kcal"] < C.info(ctx, heavy)["nutrition"]["kcal"] * 0.8]
                if pool:
                    pick = max(pool, key=lambda c: C.score(ctx, c, day, meal, variant, state))
                    ops.append({"op": "replace", "day": day, "meal": meal, "dish": heavy["name"], "with": pick["name"]})
                elif len(m["dishes"]) > 2:
                    ops.append({"op": "remove", "day": day, "meal": meal, "dish": heavy["name"]})
            elif issue["kind"] == "no_suitable_dish":
                diner = ctx.diner(issue["diner"])
                pick = C.best_for_slot(ctx, slot_main, meal, day, variant, state, exclude=names, diner=diner)
                if pick:
                    ops.append({"op": "add", "day": day, "meal": meal, "dish": pick["name"], "for_diner": diner.id})
        return ops
