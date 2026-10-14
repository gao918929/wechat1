"""Energy / macro targets (Chinese DRIs 2023) and nutrient calculation from the wiki."""
from __future__ import annotations

from collections.abc import Iterable

from ..wiki import NUTRIENT_KEYS, Wiki

GOAL_MODEL = {"fat_loss": "fat_loss", "muscle_gain": "muscle_gain", "stomach": "light_stomach", "maintain": None}
SPECIAL_LABELS = {"pregnancy": "孕妇", "child_growth": "儿童", "chronic_control": "三高/控糖人群"}

DISCLAIMER = ("本方案为一般性膳食建议，不作为医疗诊断依据。慢病人群及特殊需求人群请遵医嘱。"
              "（依据《中国居民膳食指南（2022）》与《中国居民膳食营养素参考摄入量（2023版）》）")


def diner_model_ids(diner: dict) -> list[str]:
    ids = list(dict.fromkeys(diner.get("dietary_groups") or []))
    goal_model = GOAL_MODEL.get(diner.get("goal") or "maintain")
    if goal_model and goal_model not in ids:
        ids.insert(0, goal_model)
    return ids


def bmr(sex: str, weight: float, height: float, age: float) -> float:
    """Mifflin-St Jeor."""
    base = 10 * weight + 6.25 * height - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base - 78  # midpoint when sex is unknown


def daily_targets(diner: dict, wiki: Wiki) -> dict:
    ids = [i for i in diner_model_ids(diner) if i in wiki.diet_models]
    models = [wiki.diet_models[i] for i in ids]
    notes: list[str] = []
    sex = diner.get("sex") or ""
    weight, height = diner.get("weight_kg"), diner.get("height_cm")
    age = diner.get("age") or 25
    activity = wiki.activity_factors.get(diner.get("activity_level") or "light", 1.375)

    factor = 1.0
    for m in models:
        factor *= m.num("kcal_factor", 1.0) or 1.0
    delta = sum(m.num("kcal_delta", 0.0) or 0.0 for m in models)
    if "pregnancy" in ids and factor < 1.0:
        factor = 1.0
        notes.append("孕期/哺乳期不建议制造能量缺口，已忽略减脂系数（特殊人群需求优先）。")

    estimated = False
    if weight and height:
        base = bmr(sex, weight, height, age)
        kcal = base * activity * factor + delta
        kcal = max(kcal, base) if factor < 1 else kcal
        basis = f"Mifflin-St Jeor 基础代谢 {base:.0f} kcal × 活动系数 {activity} × 人群系数 {factor:.2f}" + (
            f" + {delta:.0f}" if delta else "")
    else:
        key = {"male": "default_male", "female": "default_female"}.get(sex, "default_unknown")
        d = wiki.default_targets.get(key, {"kcal": 1950, "protein_g": 60})
        portion = 1.0
        for m in models:
            portion *= m.num("portion_factor", 1.0) or 1.0
        kcal = d["kcal"] * factor * portion + delta
        estimated = True
        basis = f"未填写身高体重，采用 DRIs 推荐值 {d['kcal']:.0f} kcal（估算）"

    protein = None
    for m in models:
        per_kg = m.num("protein_g_per_kg")
        if per_kg and weight:
            protein = max(protein or 0, per_kg * weight)
    if protein is None:
        key = {"male": "default_male", "female": "default_female"}.get(sex, "default_unknown")
        protein = (wiki.default_targets.get(key) or {}).get("protein_g") or 60
        if not (weight and height):
            portion = 1.0
            for m in models:
                portion *= m.num("portion_factor", 1.0) or 1.0
            protein *= portion
    protein += sum(m.num("protein_delta_g", 0.0) or 0.0 for m in models)

    fat_pct = min([m.num("fat_pct", 27) or 27 for m in models] or [27])
    fat_g = kcal * fat_pct / 100 / 9
    carb_g = max(0.0, (kcal - protein * 4 - fat_g * 9) / 4)

    def lim(key: str, default: float) -> float:
        return min([m.num(key, default) or default for m in models] or [default])

    return {
        "kcal": round(kcal), "protein_g": round(protein), "fat_g": round(fat_g), "carb_g": round(carb_g),
        "fat_pct": fat_pct, "oil_g_max": lim("oil_g_max", 28), "salt_g_max": lim("salt_g_max", 5),
        "sugar_g_max": lim("sugar_g_max", 50), "models": ids, "basis": basis, "estimated": estimated,
        "notes": notes,
    }


def meal_target(daily: dict, meal: str, wiki: Wiki) -> dict:
    share = wiki.meal_shares.get(meal, 0.3)
    return {"kcal": round(daily["kcal"] * share), "protein_g": round(daily["protein_g"] * share, 1),
            "fat_g": round(daily["fat_g"] * share, 1), "carb_g": round(daily["carb_g"] * share, 1),
            "share": share}


def nutrition_of(ingredients: Iterable[tuple[str, float]], wiki: Wiki) -> dict:
    """Sum nutrients for [(ingredient name, grams)]. Unknown ingredients are reported, not guessed."""
    total = {k: 0.0 for k in NUTRIENT_KEYS}
    oil = sugar = veg = 0.0
    unknown = []
    for name, grams in ingredients:
        ing = wiki.ingredient(name)
        if ing is None:
            unknown.append(name)
            continue
        for k in NUTRIENT_KEYS:
            total[k] += ing.nutrition.get(k, 0.0) * grams / 100
        if "oil" in ing.tags:
            oil += grams
        if "high_sugar" in ing.tags and ing.section == "seasonings":
            sugar += grams
        if ing.section == "vegetables" and "starchy_vegetable" not in ing.tags:
            veg += grams
    out = {k: round(v, 1) for k, v in total.items()}
    out.update({"salt_g": round(total["na"] * 2.54 / 1000, 2), "oil_g": round(oil, 1),
                "added_sugar_g": round(sugar, 1), "vegetable_g": round(veg), "unknown": unknown})
    return out


def add_nutrition(a: dict, b: dict, factor: float = 1.0) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(out.get(k, 0) + v * factor, 2)
    return out


def health_score(intake: dict, daily: dict) -> dict:
    """0–100 dietary score for one day of intake vs. targets, with the reasons for deductions."""
    score, reasons = 100.0, []
    kcal_t = daily["kcal"] or 1
    dev = abs(intake.get("kcal", 0) - kcal_t) / kcal_t
    if dev > 0.1:
        p = min(30, (dev - 0.1) * 100)
        score -= p
        reasons.append(f"能量偏离目标 {dev:.0%}")
    prot = intake.get("protein", 0)
    if prot < daily["protein_g"] * 0.9:
        p = min(20, (1 - prot / max(daily["protein_g"], 1)) * 50)
        score -= p
        reasons.append("蛋白质不足")
    kcal = intake.get("kcal", 0) or 1
    fat_pct = intake.get("fat", 0) * 9 / kcal * 100
    if fat_pct > 32 or (intake.get("kcal", 0) > 0 and fat_pct < 18):
        score -= min(15, abs(fat_pct - 25) / 2)
        reasons.append(f"脂肪供能比 {fat_pct:.0f}%（建议 20–30%）")
    if intake.get("salt_g", 0) > daily["salt_g_max"]:
        score -= min(15, (intake["salt_g"] - daily["salt_g_max"]) * 5)
        reasons.append("食盐超标")
    if intake.get("vegetable_g", 0) < 300:
        score -= min(20, (300 - intake.get("vegetable_g", 0)) / 15)
        reasons.append("蔬菜不足 300 g")
    return {"score": max(0, round(score)), "reasons": reasons}
