import asyncio
from datetime import date

from app.agents import dishes as D
from app.agents.context import PlanningContext, make_diner
from app.agents.orchestrator import run_plan
from app.llm import LLMClient
from app.services.nl import parse_plan_instruction

from .test_wiki_and_parsers import DEMO_ZH


def make_ctx(wiki, diners, *, llm=None, inventory=None, budget=None, days=7, meals=("dinner",), twin=None,
             options=None, parsed=None):
    events = []

    async def emit(t, d):
        events.append((t, d))

    ctx = PlanningContext(
        wiki=wiki, llm=llm or LLMClient(offline=True), instruction="", parsed=parsed or {}, diners=diners, days=days,
        meals=list(meals), start_date=date(2026, 10, 14), inventory=inventory or [], history={},
        budget=budget or {"mode": "per_person", "amount": 0, "total": None}, twin=twin or {}, overrides=set(),
        options=options or {"alternatives": "always"}, emit=emit)
    return ctx, events


def demo_diners(wiki):
    p = parse_plan_instruction(DEMO_ZH, wiki)
    me = {"sex": "male", "age": 21, "height_cm": 175, "weight_kg": 72, "goal": "fat_loss", "avoidances": p["avoid"]}
    return [make_diner("u1", "我", me, wiki, set())] + [
        make_diner(f"g{i}", f"同伴{i}", {"goal": "fat_loss"}, wiki, set(), is_guest=True) for i in (1, 2, 3)]


DEMO_INVENTORY = [
    {"name": "鸡胸肉", "grams": 500, "days_left": 1, "level": "near_expiry", "known": True, "estimated": True},
    {"name": "番茄", "grams": 450, "days_left": 5, "level": "ok", "known": True},
    {"name": "鸡蛋", "grams": 300, "days_left": 20, "level": "ok", "known": True},
]


def all_dishes(variant):
    return [x for d in variant["days"] for m in d["meals"] for x in m["dishes"]]


def test_demo_script_offline(wiki):
    ctx, events = make_ctx(wiki, demo_diners(wiki), inventory=DEMO_INVENTORY,
                           budget={"mode": "per_person", "amount": 80, "total": 320})
    result = asyncio.run(run_plan(ctx))
    assert result["mode"] == "rules"
    assert [v["key"] for v in result["variants"]] and len(result["variants"]) == 3
    types = [t for t, _ in events]
    assert types.index("framework") < types.index("day") < types.index("shopping")  # framework → days → shopping
    assert sum(1 for t in types if t == "agent") == 4
    for v in result["variants"]:
        assert v["validation"]["passed"], v["validation"]["issues"][:3]
        assert v["summary"]["within_budget"]
        assert not v["differentiated"]
        for dish in all_dishes(v):
            labels = D.labels_all(dish, wiki)
            assert "spicy" not in labels and "seafood" not in labels, dish["name"]
            assert "suitable_for" not in dish  # everyone-compatible plans carry no labels
        used = {u["name"]: u["day"] for u in v["summary"]["near_expiry_used"]}
        assert used.get("鸡胸肉", 99) <= 2
        assert len(v["days"]) == 7 and all(len(d["meals"]) == 1 for d in v["days"])
    assert result["recommended"] == "balanced"
    assert "医疗" in result["disclaimer"]


def test_hard_constraints_veto_including_seasonings(wiki):
    diner = make_diner("u1", "A", {"allergens": ["seafood", "peanut"]}, wiki, set())
    ctx, _ = make_ctx(wiki, [diner], days=3, meals=("lunch", "dinner"))
    result = asyncio.run(run_plan(ctx))
    excluded = {e["dish"] for e in result["excluded"]}
    assert {"宫保鸡丁", "香菇青菜", "白灼虾"} <= excluded  # peanut / oyster sauce / shrimp
    for v in result["variants"]:
        for dish in all_dishes(v):
            assert not ({"seafood", "peanut"} & D.labels_all(dish, wiki)), dish["name"]


def test_soft_constraint_override(wiki):
    diner = make_diner("u1", "A", {"avoidances": ["spicy"]}, wiki, overrides={"spicy"})
    assert "spicy" not in diner.avoid


def test_differentiated_mode_for_pregnant_member(wiki):
    diners = [make_diner("u1", "小王", {"sex": "female", "dietary_groups": ["pregnancy"]}, wiki, set()),
              make_diner("u2", "小李", {"sex": "male", "likes": ["spicy"]}, wiki, set()),
              make_diner("u3", "小张", {"sex": "male", "avoidances": ["fatty_meat"]}, wiki, set())]
    ctx, _ = make_ctx(wiki, diners, days=3, meals=("dinner",))
    result = asyncio.run(run_plan(ctx))
    assert result["differentiated"] and any("孕妇" in r for r in result["diff_reasons"])
    v = result["variants"][0]
    for d in v["days"]:
        for m in d["meals"]:
            assert all("label" in x and "suitable_for" in x for x in m["dishes"])
            assert any("小王" in x["suitable_for"] for x in m["dishes"] if x["kind"] in ("main", "one_pot"))
            assert m["diners"]["u1"]["target"]["kcal"] > m["diners"]["u3"]["target"]["kcal"] * 0.5


def test_budget_overrun_triggers_budget_agent(wiki):
    diners = [make_diner(f"u{i}", f"P{i}", {"goal": "muscle_gain", "sex": "male", "weight_kg": 75, "height_cm": 178},
                         wiki, set()) for i in range(4)]
    ctx, events = make_ctx(wiki, diners, days=5, meals=("lunch", "dinner"),
                           budget={"mode": "total", "amount": 230, "total": 230}, options={"alternatives": "auto"})
    result = asyncio.run(run_plan(ctx))
    revisions = [d for t, d in events if t == "revision"]
    agents_used = {r["agent"] for rev in revisions for r in rev["rounds"]}
    assert "budget" in agents_used
    budget_variant = next(v for v in result["variants"] if v["key"] == "budget")
    balanced = next(v for v in result["variants"] if v["key"] == "balanced")
    assert budget_variant["summary"]["total_cost"] <= balanced["summary"]["total_cost"] + 1
    assert result["conflicts"]  # alternatives were generated because of a real conflict


def test_twin_preferences_shift_choices(wiki):
    diner = make_diner("u1", "A", {}, wiki, set())
    base_ctx, _ = make_ctx(wiki, [diner], days=7, meals=("dinner",), options={"alternatives": "never"})
    base = asyncio.run(run_plan(base_ctx))
    base_count = sum(1 for x in all_dishes(base["variants"][0]) if x["name"] == "番茄炖牛肉")
    twin = {"dish_scores": {"番茄炖牛肉": 6, "香煎鸡胸肉": -4}, "feedback_count": 5, "version": "1.1",
            "variant_choices": {"budget": 3}}
    ctx, _ = make_ctx(wiki, [diner], days=7, meals=("dinner",), twin=twin, options={"alternatives": "always"})
    result = asyncio.run(run_plan(ctx))
    names = [x["name"] for x in all_dishes(next(v for v in result["variants"] if v["key"] == "balanced"))]
    assert names.count("番茄炖牛肉") >= max(1, base_count)
    assert "香煎鸡胸肉" not in names
    assert result["variants"][0]["key"] == "budget"  # twin-weighted ranking
    assert "已学习 5 条反馈" in result["agents"]["iterative"]["summary"]


def test_each_agent_makes_its_own_llm_call(wiki, fake_llm_cls):
    """Genuine multi-agent architecture: four agents → four independent calls with their own prompts."""
    llm = fake_llm_cls({
        "health": {"summary": "LLM 健康建议", "recommended_dishes": ["番茄炖鸡胸", "不存在的菜"], "notes": ["多吃蔬菜"]},
        "inventory": {"summary": "LLM 库存安排", "schedule": [{"name": "鸡胸肉", "use_by_day": 1, "suggested_dishes": ["香煎鸡胸肉"]}]},
        "budget": {"summary": "LLM 预算策略", "budget_friendly_dishes": ["番茄炒蛋"], "strategy": "多用鸡蛋豆腐"},
        "iterative": {"summary": "LLM 迭代优化", "favor_dishes": ["蒜蓉西兰花"]},
        "orchestrator": lambda payload: {"days": [{"day": d, "meals": [{"meal": "dinner", "dishes": [
            "香煎鸡胸肉" if d == 1 else "番茄炖鸡胸", "蒜蓉西兰花", "杂粮饭"]}]} for d in (1, 2, 3)], "notes": "测试"},
    })
    ctx, events = make_ctx(wiki, demo_diners(wiki), llm=llm, days=3, inventory=DEMO_INVENTORY,
                           budget={"mode": "per_person", "amount": 80, "total": 320}, options={"alternatives": "never"})
    result = asyncio.run(run_plan(ctx))
    agents_called = [c["agent"] for c in llm.log]
    assert {"health", "inventory", "budget", "iterative"} <= set(agents_called)
    assert agents_called.count("orchestrator") >= 1
    prompts = {c["agent"]: c["system"] for c in llm.log}
    assert len({prompts[a] for a in ("health", "inventory", "budget", "iterative")}) == 4  # separate system prompts
    assert result["mode"] == "llm"
    assert result["agents"]["health"]["recommended_dishes"] == ["番茄炖鸡胸"]  # unknown names filtered out
    v = result["variants"][0]
    assert v["composer"] == "llm"
    assert v["days"][0]["meals"][0]["dishes"][0]["name"] == "香煎鸡胸肉"
