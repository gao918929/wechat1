"""Base class for the four planning agents.

Each agent owns its system prompt and makes its **own** LLM call with its own context (no
multi-agent role-play inside one prompt). Deterministic rules compute the facts an agent is
grounded on (targets, costs, expiry dates) and serve as the fallback when the LLM is offline
or fails; the LLM adds judgement on top (which dishes, which schedule, which substitutions).
"""
from __future__ import annotations

import time

from ..llm import LLMError
from . import composer as C
from .context import PlanningContext

OPS_SPEC = """修订操作（ops）格式，只能引用候选菜名称或给出含 ingredients 的新菜对象：
{"op":"replace","day":1,"meal":"dinner","dish":"原菜名","with":"候选菜名"}
{"op":"add","day":1,"meal":"dinner","dish":"候选菜名","for_diner":"可选，就餐者id"}
{"op":"remove","day":1,"meal":"dinner","dish":"菜名"}
{"op":"substitute","dish":"菜名或*","from":"食材","to":"食材","day":可选,"meal":可选}
输出 JSON：{"ops":[...],"explanation":"一句话"}"""


class Agent:
    key = ""
    title = ""
    priority = 0
    system_prompt = ""

    # -- to implement
    def rules_analyze(self, ctx: PlanningContext) -> dict:
        raise NotImplementedError

    def analyze_payload(self, ctx: PlanningContext, base: dict) -> dict:
        raise NotImplementedError

    def merge(self, ctx: PlanningContext, base: dict, resp: dict) -> dict:
        return {**base, **{k: v for k, v in resp.items() if v not in (None, "", [])}}

    def rules_revise(self, ctx: PlanningContext, draft: dict, issues: list[dict], variant: str) -> list[dict]:
        return []

    # -- shared machinery
    def _known_names(self, ctx: PlanningContext, names) -> list[str]:
        known = {c["name"] for c in ctx.candidates}
        return [n for n in (names or []) if isinstance(n, str) and n in known]

    async def analyze(self, ctx: PlanningContext) -> dict:
        started = time.monotonic()
        base = self.rules_analyze(ctx)
        out = {**base, "agent": self.key, "title": self.title, "mode": "rules"}
        if ctx.llm.online:
            try:
                resp = await ctx.llm.chat_json(self.system_prompt, self.analyze_payload(ctx, base), agent=self.key)
                out = {**self.merge(ctx, base, resp if isinstance(resp, dict) else {}),
                       "agent": self.key, "title": self.title, "mode": "llm"}
            except LLMError as exc:
                out["llm_error"] = str(exc)[:200]
                ctx.warnings.append(f"{self.title} LLM 调用失败，已使用规则结果。")
        out["seconds"] = round(time.monotonic() - started, 2)
        ctx.agent_outputs[self.key] = out
        await ctx.emit("agent", {"agent": self.key, "title": self.title, "mode": out["mode"],
                                 "summary": out.get("summary", ""), "seconds": out["seconds"]})
        return out

    async def revise(self, ctx: PlanningContext, draft: dict, issues: list[dict], variant: str) -> tuple[list[dict], str]:
        """Return (ops, mode). The LLM proposes ops first; invalid/empty output falls back to rules."""
        if ctx.llm.online:
            payload = {
                "variant": variant, "issues": [i["message"] for i in issues][:30],
                "issue_details": issues[:30],
                "plan": [{"day": d["day"], "meals": [{"meal": m["meal"], "dishes": [x["name"] for x in m["dishes"]]}
                                                      for m in d["meals"]]} for d in draft["days"]],
                "candidates": [C.D.brief(c, ctx.wiki, ctx.history) for c in ctx.candidates],
                "diners": [{"id": d.id, "name": d.name, "special": d.special} for d in ctx.diners],
            }
            try:
                resp = await ctx.llm.chat_json(self.system_prompt + "\n\n现在校验未通过，请给出修订。\n" + OPS_SPEC,
                                               payload, agent=self.key)
                ops = [o for o in (resp.get("ops") or []) if isinstance(o, dict) and o.get("op")]
                if ops:
                    return ops, "llm"
            except LLMError as exc:
                ctx.warnings.append(f"{self.title} 修订调用失败（{str(exc)[:60]}），改用规则修订。")
        return self.rules_revise(ctx, draft, issues, variant), "rules"


def meal_of(draft: dict, day: int, meal: str) -> dict | None:
    return C._find_meal(draft, day, meal)


def state_from_draft(ctx: PlanningContext, draft: dict) -> dict:
    state = C._new_state(ctx)
    for d in draft["days"]:
        for m in d["meals"]:
            for x in m["dishes"]:
                C._take(ctx, state, x, d["day"])
    return state
