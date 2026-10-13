"""Iterative Optimization Agent (priority 2): learn from the digital twin to improve over time."""
from __future__ import annotations

from .base import Agent
from .context import PlanningContext


class IterativeAgent(Agent):
    key = "iterative"
    title = "迭代优化智能体"
    priority = 2
    system_prompt = """你是 MealAgent 的【迭代优化智能体】，职责：读取数字孪生中的口味偏好、历史评分、收藏、删除与替换记录，
调整菜品风格与组合，让方案越用越懂用户。不得推荐违反过敏原/禁忌的菜；只能按名称引用候选菜。
输出 JSON：{"summary":"一句话","favor_dishes":[...],"avoid_dishes":[...],"favor_ingredients":[...],
"avoid_ingredients":[...],"substitutions":[{"from":"食材","to":"食材"}],"style_notes":"..."}"""

    def rules_analyze(self, ctx: PlanningContext) -> dict:
        twin = ctx.twin or {}
        dish_scores = twin.get("dish_scores", {})
        ing_scores = twin.get("ingredient_scores", {})
        known = {c["name"] for c in ctx.candidates}
        favor = [n for n, s in sorted(dish_scores.items(), key=lambda kv: -kv[1]) if s >= 1 and n in known][:10]
        avoid = [n for n, s in sorted(dish_scores.items(), key=lambda kv: kv[1]) if s <= -1][:10]
        favor_i = [n for n, s in ing_scores.items() if s >= 1]
        avoid_i = [n for n, s in ing_scores.items() if s <= -1]
        subs = [{"from": s["from"], "to": s["to"]} for s in twin.get("substitutions", []) if s.get("count", 0) >= 2]
        recent = twin.get("recent_dishes", [])[:14]
        n_feedback = twin.get("feedback_count", 0)
        if n_feedback:
            summary = f"已学习 {n_feedback} 条反馈：偏好 {('、'.join(favor[:3]) or '—')}；回避 {('、'.join(avoid[:3]) or '—')}"
            if subs:
                summary += "；替换习惯 " + "、".join(f"{s['from']}→{s['to']}" for s in subs[:2])
        else:
            summary = "暂无历史反馈（首次使用），按人群模型默认偏好；从下周起将根据评价自动优化"
        return {"summary": summary, "dish_scores": {n: v for n, v in dish_scores.items() if n in known},
                "favor_dishes": favor, "avoid_dishes": avoid, "favor_ingredients": favor_i,
                "avoid_ingredients": avoid_i, "substitutions": subs, "recent_dishes": recent,
                "variant_choices": twin.get("variant_choices", {}), "style_notes": twin.get("style_notes", ""),
                "feedback_count": n_feedback}

    def analyze_payload(self, ctx: PlanningContext, base: dict) -> dict:
        twin = ctx.twin or {}
        return {
            "twin": {k: twin.get(k) for k in ("dish_scores", "ingredient_scores", "substitutions", "favorites",
                                               "recent_dishes", "variant_choices", "price_sensitivity", "diner_pattern")},
            "rules_summary": base,
            "candidates": [{"name": c["name"], "kind": c["kind"], "tags": c.get("tags", [])} for c in ctx.candidates],
        }

    def merge(self, ctx: PlanningContext, base: dict, resp: dict) -> dict:
        out = dict(base)
        out["summary"] = resp.get("summary") or base["summary"]
        out["favor_dishes"] = list(dict.fromkeys(base["favor_dishes"] + self._known_names(ctx, resp.get("favor_dishes"))))
        out["avoid_dishes"] = list(dict.fromkeys(base["avoid_dishes"] + [n for n in resp.get("avoid_dishes") or [] if isinstance(n, str)]))
        for key in ("favor_ingredients", "avoid_ingredients"):
            extra = [ctx.wiki.resolve(n) for n in resp.get(key) or [] if isinstance(n, str)]
            out[key] = list(dict.fromkeys(base[key] + [n for n in extra if n]))
        subs = [s for s in resp.get("substitutions") or [] if isinstance(s, dict) and ctx.wiki.resolve(s.get("from", ""))
                and ctx.wiki.resolve(s.get("to", ""))]
        out["substitutions"] = base["substitutions"] + [{"from": ctx.wiki.resolve(s["from"]), "to": ctx.wiki.resolve(s["to"])} for s in subs]
        out["style_notes"] = resp.get("style_notes") or base["style_notes"]
        return out
