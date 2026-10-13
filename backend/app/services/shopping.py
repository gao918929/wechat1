"""Shopping list: plan needs − inventory, grouped by supermarket section, with cost per person."""
from __future__ import annotations

import math

from ..wiki import SECTION_LABELS, SECTION_ORDER, Wiki
from .pricing import unit_price

PIECE_UNIT = {"tofu": "块", "dairy": "盒", "bakery": "个"}


def _by_piece(ing) -> bool:
    """Sold by the piece (eggs, tomatoes, tofu blocks…) rather than by weight (meat, leafy greens…)."""
    if not ing.piece_g or not 45 <= ing.piece_g <= 600 or ing.shelf in ("leafy", "mushroom"):
        return False
    if ing.section == "meat_eggs":
        return ing.shelf == "eggs"
    return ing.section not in ("seafood", "seasonings")


def _round_purchase(buy_g: float, piece_g: float | None, unit: str = "个") -> tuple[float, str]:
    if piece_g:
        pieces = max(1, math.ceil(buy_g / piece_g - 0.15))
        return pieces * piece_g, f"{pieces} {unit}（约 {pieces * piece_g:.0f} g）"
    step = 100 if buy_g >= 500 else 50
    g = max(step, math.ceil(buy_g / step) * step)
    return g, f"{g / 500:.1f} 斤（{g:.0f} g）" if g >= 500 else f"{g:.0f} g"


def build_shopping(need: dict[str, float], inventory: list[dict], history: dict[str, float], wiki: Wiki,
                   people: int, budget_total: float | None) -> dict:
    inv = {it["name"]: it for it in inventory}
    sections: dict[str, list[dict]] = {}
    pantry, covered, unknown = [], [], []
    total, estimated = 0.0, False
    for name, grams in sorted(need.items()):
        ing = wiki.ingredient(name)
        if ing is None:
            unknown.append(name)
            continue
        have = (inv.get(ing.name) or {}).get("grams") or 0.0
        if ing.is_pantry:
            pantry.append({"name": ing.name, "need_g": round(grams), "in_stock": ing.name in inv})
            continue
        buy = grams - have
        if buy <= max(5.0, grams * 0.05):
            covered.append({"name": ing.name, "need_g": round(grams), "have_g": round(have)})
            continue
        buy_g, qty_text = _round_purchase(buy, ing.piece_g if _by_piece(ing) else None, PIECE_UNIT.get(ing.shelf, "个"))
        price = unit_price(ing.name, history, wiki)
        cost = round((price["unit_price"] or 0) * buy_g / 1000, 2)
        total += cost
        estimated = estimated or price["estimated"]
        sections.setdefault(ing.section, []).append({
            "name": ing.name, "section": ing.section, "need_g": round(grams), "have_g": round(have),
            "buy_g": round(buy_g), "qty_text": qty_text, "unit_price": price["unit_price"],
            "price_source": price["source"], "price_estimated": price["estimated"], "cost": cost,
        })
    ordered = [{"section": s, "label": SECTION_LABELS.get(s, s), "items": sections[s]}
               for s in SECTION_ORDER if s in sections]
    total = round(total, 2)
    people = max(1, people)
    return {
        "sections": ordered, "pantry": pantry, "covered_by_inventory": covered, "unknown": unknown,
        "total_cost": total, "per_person_cost": round(total / people, 2), "people": people,
        "budget_total": budget_total, "over_budget": bool(budget_total and total > budget_total),
        "over_amount": round(total - budget_total, 2) if budget_total and total > budget_total else 0.0,
        "estimated": estimated,
    }


def shopping_text(shopping: dict, title: str = "", checked: dict | None = None) -> str:
    checked = checked or {}
    lines = [f"【MealAgent 购物清单】{title}".strip()]
    for sec in shopping["sections"]:
        lines.append(f"— {sec['label']} —")
        for it in sec["items"]:
            mark = "☑" if checked.get(it["name"]) else "□"
            est = "（估算）" if it["price_estimated"] else ""
            lines.append(f"{mark} {it['name']} {it['qty_text']}  ¥{it['cost']:.2f}{est}")
    lines.append(f"合计 ¥{shopping['total_cost']:.2f} ｜ 人均 ¥{shopping['per_person_cost']:.2f}（{shopping['people']} 人）")
    if shopping.get("budget_total"):
        if shopping["over_budget"]:
            lines.append(f"⚠ 超出预算 ¥{shopping['over_amount']:.2f}（预算 ¥{shopping['budget_total']:.0f}）")
        else:
            lines.append(f"预算 ¥{shopping['budget_total']:.0f}，剩余 ¥{shopping['budget_total'] - shopping['total_cost']:.2f}")
    if shopping["pantry"]:
        lines.append("常备调料检查：" + "、".join(p["name"] for p in shopping["pantry"]))
    if shopping["covered_by_inventory"]:
        lines.append("库存已有（无需购买）：" + "、".join(c["name"] for c in shopping["covered_by_inventory"]))
    if shopping["estimated"]:
        lines.append("注：部分价格为参考价（估算），以实际购买为准。")
    return "\n".join(lines)
