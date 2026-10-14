"""Central Orchestrator: dispatch the four agents, compose, validate/rollback, multi-plan output."""
from __future__ import annotations

import asyncio
import hashlib
import json

from ..config import settings
from ..services.nutrition import DISCLAIMER
from . import composer as C
from .budget import BudgetAgent
from .context import PlanningContext, label_text, prepare
from .health import HealthAgent
from .inventory import InventoryAgent
from .iterative import IterativeAgent
from .validator import suggestions, validate

DEFAULT_ORDER = ["balanced", "health", "budget"]


def make_agents() -> list:
    return sorted([HealthAgent(), IterativeAgent(), InventoryAgent(), BudgetAgent()], key=lambda a: a.priority)


async def build_variant(ctx: PlanningContext, key: str, agents: list) -> dict:
    draft = await C.compose(ctx, key)
    revisions = []
    max_retries = ctx.options.get("max_retries", settings.max_validation_retries)
    attempt = 0
    while True:
        variant = C.finalize(ctx, draft)
        report = validate(ctx, variant)
        await ctx.emit("validation", {"variant": key, "attempt": attempt, "passed": report["passed"],
                                      "layers": report["layers"], "issues": [i["message"] for i in report["issues"][:6]]})
        if report["passed"] or attempt >= max_retries:
            break
        attempt += 1
        by_agent: dict[str, list] = {}
        for issue in report["issues"]:
            by_agent.setdefault(issue["agent"], []).append(issue)
        round_log = []
        for agent in agents:  # priority order: health → iterative → inventory → budget
            if agent.key not in by_agent:
                continue
            ops, mode = await agent.revise(ctx, draft, by_agent[agent.key], key)
            applied = C.apply_ops(ctx, draft, ops)
            round_log.append({"agent": agent.key, "title": agent.title, "mode": mode, "applied": applied})
        revisions.append({"attempt": attempt, "rounds": round_log})
        await ctx.emit("revision", {"variant": key, "attempt": attempt, "rounds": round_log})
        if not any(r["applied"] for r in round_log):
            variant = C.finalize(ctx, draft)
            report = validate(ctx, variant)
            break
    variant["validation"] = {**report, "attempts": attempt + 1, "revisions": revisions}
    if not report["passed"]:
        variant["validation"]["suggestions"] = suggestions(ctx, variant, report)
    return variant


def detect_conflicts(ctx: PlanningContext, balanced: dict) -> list[str]:
    out = []
    s = balanced["summary"]
    if not balanced["validation"]["passed"]:
        out.append("平衡方案仍有未满足的约束")
    if s.get("budget_utilization") and s["budget_utilization"] > 0.9:
        out.append(f"预算使用率 {s['budget_utilization']:.0%}，预算偏紧")
    if s["near_expiry_unused"]:
        out.append("部分临期食材难以全部用掉")
    if balanced["validation"]["revisions"]:
        out.append("营养/库存/预算之间存在取舍（已触发校验回退）")
    if ctx.differentiated:
        out.append("就餐者需求不同（差异化多菜）")
    return out


def rank(ctx: PlanningContext, variants: list[dict]) -> list[dict]:
    """Twin-weighted ranking: plans that match historical choices come first."""
    choices = (ctx.twin or {}).get("variant_choices", {})
    ordered = sorted(variants, key=lambda v: (not v["validation"]["passed"], -choices.get(v["key"], 0),
                                              DEFAULT_ORDER.index(v["key"])))
    for i, v in enumerate(ordered):
        v["rank"] = i + 1
        v["recommended"] = i == 0
    return ordered


def cache_key(ctx: PlanningContext) -> str:
    payload = {
        "diners": [d.public() for d in ctx.diners], "days": ctx.days, "meals": ctx.meals,
        "start": ctx.start_date.isoformat(), "budget": ctx.budget, "overrides": sorted(ctx.overrides),
        "inventory": [(i["name"], round(i["grams"] or 0, -1), i["days_left"], i["level"]) for i in ctx.inventory],
        "history": ctx.history, "twin": ctx.twin.get("version"), "options": {k: v for k, v in ctx.options.items() if k != "cache"},
        "mode": "llm" if ctx.llm.online else "rules",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _trim_agent(out: dict) -> dict:
    return {k: v for k, v in out.items() if k not in ("dish_costs",)}


async def run_plan(ctx: PlanningContext) -> dict:
    prepare(ctx)
    await ctx.emit("intent", {
        "parsed": ctx.parsed, "diners": [d.public() for d in ctx.diners], "days": ctx.days, "meals": ctx.meals,
        "budget": ctx.budget, "differentiated": ctx.differentiated, "diff_reasons": ctx.diff_reasons,
        "hard_constraints": [label_text(x) for x in sorted(ctx.hard_labels)],
        "candidates": len(ctx.candidates), "excluded": len(ctx.excluded),
        "mode": "llm" if ctx.llm.online else "rules",
    })
    agents = make_agents()
    # Phase 1 — four independent agents, each with its own LLM call, dispatched in parallel
    await asyncio.gather(*(a.analyze(ctx) for a in agents))
    await ctx.emit("framework", {
        "targets": ctx.agent_outputs["health"]["targets"],
        "inventory": ctx.agent_outputs["inventory"]["summary"],
        "budget": ctx.agent_outputs["budget"]["summary"],
        "twin": ctx.agent_outputs["iterative"]["summary"],
        "health": ctx.agent_outputs["health"]["summary"],
        "strategy": "先生成平衡方案，三层校验（库存→营养→预算）不通过则退回对应智能体重做（最多 3 次）",
    })

    balanced = await build_variant(ctx, "balanced", agents)
    variants = [balanced]
    conflicts = detect_conflicts(ctx, balanced)
    mode = ctx.options.get("alternatives", "auto")
    if mode == "always" or (mode == "auto" and conflicts):
        await ctx.emit("conflict", {"conflicts": conflicts or ["用户要求同时查看备选方案"]})
        variants += await asyncio.gather(build_variant(ctx, "health", agents), build_variant(ctx, "budget", agents))
    variants = rank(ctx, variants)

    for v in variants:
        await ctx.emit("variant", {"key": v["key"], "title": v["title"], "tradeoff": v["tradeoff"], "rank": v["rank"],
                                   "summary": v["summary"], "passed": v["validation"]["passed"]})
    top = variants[0]
    for d in top["days"]:
        await ctx.emit("day", {"variant": top["key"], "day": d})
    await ctx.emit("shopping", {"variant": top["key"], "shopping": top["shopping"]})

    return {
        "mode": "llm" if ctx.llm.online else "rules",
        "llm_usage": ctx.llm.usage_summary(),
        "parsed": ctx.parsed, "diners": [d.public() for d in ctx.diners],
        "days": ctx.days, "meals": ctx.meals, "start_date": ctx.start_date.isoformat(), "budget": ctx.budget,
        "differentiated": ctx.differentiated, "diff_reasons": ctx.diff_reasons,
        "hard_constraints": [label_text(x) for x in sorted(ctx.hard_labels)],
        "hard_constraint_labels": sorted(ctx.hard_labels),
        "excluded": ctx.excluded, "agents": {k: _trim_agent(v) for k, v in ctx.agent_outputs.items()},
        "conflicts": conflicts, "variants": variants, "recommended": top["key"],
        "warnings": list(dict.fromkeys(ctx.warnings)), "disclaimer": DISCLAIMER,
        "sources": ctx.wiki.sources_text(),
    }
