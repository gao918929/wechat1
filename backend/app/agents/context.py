"""Planning context shared by the orchestrator and the four agents.

Agents never touch the database: the orchestrator assembles everything they need here, which
also keeps each agent's LLM call self-contained (its own system prompt + its own context).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from ..llm import LLMClient
from ..services.nutrition import SPECIAL_LABELS, daily_targets, diner_model_ids, meal_target
from ..wiki import Wiki
from . import dishes as D

LABEL_TEXT = {
    "spicy": "辣", "seafood": "海鲜", "shellfish": "虾蟹贝类", "fish": "鱼", "fatty_meat": "肥肉", "pork": "猪肉",
    "beef": "牛肉", "lamb": "羊肉", "poultry": "禽肉", "organ": "内脏", "cilantro": "香菜", "peanut": "花生",
    "egg": "鸡蛋", "milk": "奶", "soy": "大豆", "wheat": "小麦", "sesame": "芝麻", "processed": "加工肉制品",
    "high_sugar": "高糖", "high_fat": "高脂", "alcohol": "酒精", "raw_risk": "生食风险", "high_mercury": "高汞鱼",
    "mollusk": "软体海鲜", "nut": "坚果", "fried": "油炸", "mango": "芒果",
}


def label_text(label: str) -> str:
    return LABEL_TEXT.get(label, label)


@dataclass
class Diner:
    id: str
    name: str
    profile: dict
    daily: dict
    models: list[str]
    allergens: set[str]
    avoid: set[str]
    likes: set[str]
    max_spicy: int
    member_avoid: set[str]
    hard_forbidden: set[str]
    special: list[str]
    is_guest: bool = False

    def meal_target(self, meal: str, wiki: Wiki) -> dict:
        return meal_target(self.daily, meal, wiki)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "daily": self.daily, "models": self.models,
                "allergens": sorted(self.allergens), "avoid": sorted(self.avoid), "special": self.special,
                "is_guest": self.is_guest}


Emit = Callable[[str, dict], Awaitable[None]]


async def _noop_emit(_t: str, _d: dict) -> None:
    return None


@dataclass
class PlanningContext:
    wiki: Wiki
    llm: LLMClient
    instruction: str
    parsed: dict
    diners: list[Diner]
    days: int
    meals: list[str]
    start_date: date
    inventory: list[dict]
    history: dict[str, float]
    budget: dict
    twin: dict
    overrides: set[str]
    hard_labels: set[str] = field(default_factory=set)
    differentiated: bool = False
    diff_reasons: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    options: dict = field(default_factory=dict)
    emit: Emit = _noop_emit
    agent_outputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    memo: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers
    def diner(self, diner_id: str) -> Diner | None:
        return next((d for d in self.diners if d.id == diner_id), None)

    def candidate(self, name: str) -> dict | None:
        return next((c for c in self.candidates if c["name"] == name), None)

    def unsuitable_reasons(self, dish: dict, diner: Diner) -> list[str]:
        """Why a (hard-constraint-safe) dish doesn't suit one diner: soft avoidances / diet model."""
        reasons = []
        for lab in D.matches(dish, diner.avoid, self.wiki, "all"):
            reasons.append(f"不吃{label_text(lab)}")
        spicy = dish.get("spicy", 0) or (1 if "spicy" in D.labels_all(dish, self.wiki) else 0)
        if spicy > diner.max_spicy and "spicy" not in diner.avoid:
            reasons.append("辣度超出接受范围")
        for lab in D.matches(dish, diner.member_avoid, self.wiki, "main"):
            who = "、".join(diner.special) or diner.name
            reasons.append(f"{who}建议回避（{label_text(lab)}）")
        return reasons

    def suitability(self, dish: dict) -> dict:
        not_for = []
        for d in self.diners:
            r = self.unsuitable_reasons(dish, d)
            if r:
                not_for.append({"diner": d.id, "name": d.name, "reasons": r})
        bad = {n["diner"] for n in not_for}
        return {"suitable_for": [d.id for d in self.diners if d.id not in bad], "not_for": not_for}

    def meal_slots(self, meal: str) -> list[str]:
        n = len(self.diners)
        if meal == "breakfast":
            return ["breakfast"] if n <= 2 else ["breakfast", "breakfast"]
        if n <= 2:
            return ["main", "veg", "staple"]
        if n == 3:
            return ["main", "main", "veg", "staple"]
        return ["main", "main", "veg", "soup", "staple"]

    def budget_total(self) -> float | None:
        return self.budget.get("total")


def make_diner(did: str, name: str, profile: dict, wiki: Wiki, overrides: set[str], is_guest: bool = False) -> Diner:
    models = [m for m in diner_model_ids(profile) if m in wiki.diet_models]
    member_avoid, hard, special = set(), set(), []
    for mid in models:
        dm = wiki.diet_models[mid]
        member_avoid |= dm.tags("member_avoid")
        hard |= dm.tags("hard_forbidden")
        if dm.flag("special_need"):
            special.append(SPECIAL_LABELS.get(mid, dm.name))
    avoid = set(profile.get("avoidances") or []) - overrides
    return Diner(
        id=did, name=name, profile=profile, daily=daily_targets(profile, wiki), models=models,
        allergens=set(profile.get("allergens") or []), avoid=avoid, likes=set(profile.get("likes") or []),
        max_spicy=int(profile.get("max_spicy", 3) if profile.get("max_spicy") is not None else 3),
        member_avoid=member_avoid - overrides, hard_forbidden=hard, special=special, is_guest=is_guest,
    )


def prepare(ctx: PlanningContext) -> None:
    """Derive hard labels, the differentiated-mode decision and the candidate dish pool."""
    wiki = ctx.wiki
    ctx.hard_labels = set()
    for d in ctx.diners:
        ctx.hard_labels |= d.allergens | d.hard_forbidden

    reasons = []
    for d in ctx.diners:
        if d.special:
            reasons.append(f"{d.name}属于特殊需求人群（{'、'.join(d.special)}）")
        for mid in d.models:
            if wiki.diet_models[mid].flag("triggers_differentiated") and len(ctx.diners) > 1:
                reasons.append(f"{d.name}为{wiki.diet_models[mid].name}，与其他人饮食不同")
    for a in ctx.diners:
        for b in ctx.diners:
            if a is b:
                continue
            clash = a.avoid & b.likes
            for lab in sorted(clash):
                reasons.append(f"软约束冲突：{a.name}不吃{label_text(lab)}，{b.name}爱吃")
    ctx.diff_reasons = list(dict.fromkeys(reasons))
    ctx.differentiated = bool(ctx.diff_reasons) and len(ctx.diners) > 1

    ctx.candidates, ctx.excluded = [], []
    for t in wiki.dishes.values():
        dish = D.from_template(t)
        if not set(t.meals) & set(ctx.meals):
            continue
        hard = D.matches(dish, ctx.hard_labels, wiki, "all")
        if hard:
            ctx.excluded.append({"dish": dish["name"], "reason": "硬约束一票否决：含" + "、".join(label_text(h) for h in hard)})
            continue
        if not ctx.differentiated:
            soft = []
            for d in ctx.diners:
                soft += [f"{d.name}：{r}" for r in ctx.unsuitable_reasons(dish, d)]
            if soft:
                ctx.excluded.append({"dish": dish["name"], "reason": "软约束默认回避（可推翻）：" + "；".join(soft)})
                continue
        ctx.candidates.append(dish)
    if ctx.differentiated:
        # every special/divergent diner must have something to eat in each slot kind
        for d in ctx.diners:
            ok = [c for c in ctx.candidates if not ctx.unsuitable_reasons(c, d) and c["kind"] in ("main", "one_pot", "breakfast")]
            if not ok:
                ctx.warnings.append(f"候选菜中没有适合{d.name}的主菜，请调整忌口或补充菜谱。")
