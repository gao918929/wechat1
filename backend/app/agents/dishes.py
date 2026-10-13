"""Dish helpers shared by the agents: labels, constraint matching, nutrition and cost per serving."""
from __future__ import annotations

import copy

from ..services.nutrition import nutrition_of
from ..services.pricing import unit_price
from ..wiki import DishTemplate, Wiki

SUGAR_FLAG_G = 8  # added sugar per serving that makes a dish "high_sugar"


def from_template(t: DishTemplate) -> dict:
    return {
        "name": t.name, "en": t.en, "kind": t.kind, "meals": list(t.meals), "tags": sorted(t.tags),
        "spicy": t.spicy, "minutes": t.minutes, "difficulty": t.difficulty, "steps": t.steps,
        "source": t.source, "ingredients": [{"name": n, "grams": g} for n, g in t.ingredients],
    }


def normalize_custom(d: dict, wiki: Wiki) -> dict:
    """A dish proposed by the LLM (not in the template library). Ingredient names are resolved
    against the wiki; unknown ones are kept so the validator can reject them."""
    ings = []
    for i in d.get("ingredients") or []:
        if isinstance(i, dict):
            name, grams = i.get("name", ""), i.get("grams") or i.get("grams_per_serving") or 0
        else:
            name, grams = str(i), 0
        ings.append({"name": wiki.resolve(name) or name, "grams": float(grams or 0)})
    return {
        "name": d.get("name", "自定义菜"), "en": d.get("en", ""), "kind": d.get("kind", "main"),
        "meals": d.get("meals") or ["lunch", "dinner"], "tags": list(d.get("tags") or []),
        "spicy": int(d.get("spicy") or 0), "minutes": int(d.get("minutes") or 20), "difficulty": "easy",
        "steps": d.get("steps", ""), "source": "agent", "ingredients": ings,
    }


def labels_all(dish: dict, wiki: Wiki) -> set[str]:
    """Every label of every ingredient (seasonings included) — used for hard constraints and
    user-stated avoidances such as allergens or "不吃香菜"."""
    out = set(dish.get("tags") or [])
    for i in dish["ingredients"]:
        ing = wiki.ingredient(i["name"])
        out.add(i["name"])
        if ing:
            out |= ing.labels | {ing.name}
    if dish.get("spicy", 0) > 0:
        out.add("spicy")
    return out | _derived(dish, wiki)


def labels_main(dish: dict, wiki: Wiki) -> set[str]:
    """Labels from non-seasoning ingredients — used for diet-model tag preferences so that a few
    grams of soy sauce don't mark every dish ``high_salt``."""
    out = set(dish.get("tags") or [])
    for i in dish["ingredients"]:
        ing = wiki.ingredient(i["name"])
        if ing and ing.section != "seasonings":
            out |= ing.labels | {ing.name}
    if dish.get("spicy", 0) > 0 or any("spicy" in (wiki.ingredient(i["name"]).tags if wiki.ingredient(i["name"]) else ())
                                       for i in dish["ingredients"]):
        out.add("spicy")
    return out | _derived(dish, wiki)


def _derived(dish: dict, wiki: Wiki) -> set[str]:
    out = set()
    sugar = sum(i["grams"] for i in dish["ingredients"]
                if (ing := wiki.ingredient(i["name"])) and "high_sugar" in ing.tags and ing.section == "seasonings")
    if sugar >= SUGAR_FLAG_G:
        out.add("high_sugar")
    return out


def matches(dish: dict, wanted: set[str], wiki: Wiki, scope: str = "all") -> list[str]:
    """Which of ``wanted`` labels/ingredient names this dish contains."""
    if not wanted:
        return []
    have = labels_all(dish, wiki) if scope == "all" else labels_main(dish, wiki)
    return sorted(w for w in wanted if w in have)


def per_serving_nutrition(dish: dict, wiki: Wiki) -> dict:
    return nutrition_of(((i["name"], i["grams"]) for i in dish["ingredients"]), wiki)


def per_serving_cost(dish: dict, wiki: Wiki, history: dict[str, float]) -> dict:
    """Cost of one serving, excluding pantry seasonings. ``estimated`` if any reference price used."""
    total, estimated = 0.0, False
    for i in dish["ingredients"]:
        ing = wiki.ingredient(i["name"])
        if ing is None or ing.is_pantry:
            continue
        p = unit_price(ing.name, history, wiki)
        if p["unit_price"] is None:
            continue
        total += p["unit_price"] * i["grams"] / 1000
        estimated = estimated or p["estimated"]
    return {"cost": round(total, 2), "estimated": estimated}


def substitute(dish: dict, src: str, dst: str, wiki: Wiki) -> dict | None:
    """Return a copy of ``dish`` with ingredient ``src`` replaced by ``dst`` (protein-equivalent grams)."""
    src_c, dst_c = wiki.resolve(src) or src, wiki.resolve(dst) or dst
    if not any(i["name"] == src_c for i in dish["ingredients"]):
        return None
    out = copy.deepcopy(dish)
    a, b = wiki.ingredients.get(src_c), wiki.ingredients.get(dst_c)
    for i in out["ingredients"]:
        if i["name"] == src_c:
            ratio = 1.0
            if a and b and a.nutrition["protein"] > 5 and b.nutrition["protein"] > 5:
                ratio = a.nutrition["protein"] / b.nutrition["protein"]
            i["name"] = dst_c
            i["grams"] = round(i["grams"] * max(0.6, min(1.6, ratio)))
    out["name"] = dish["name"].replace(src_c, dst_c) if src_c in dish["name"] else f"{dish['name']}（{src_c}换{dst_c}）"
    out["source"] = "agent"
    out.setdefault("notes", []).append(f"{src_c} → {dst_c}")
    return out


def brief(dish: dict, wiki: Wiki, history: dict[str, float]) -> dict:
    """Compact description for LLM prompts."""
    n = per_serving_nutrition(dish, wiki)
    c = per_serving_cost(dish, wiki, history)
    return {"name": dish["name"], "kind": dish["kind"], "meals": dish.get("meals"),
            "main_ingredients": [i["name"] for i in dish["ingredients"]
                                 if (ing := wiki.ingredient(i["name"])) and ing.section != "seasonings"],
            "kcal": round(n["kcal"]), "protein": round(n["protein"], 1), "cost": c["cost"],
            "tags": sorted(labels_main(dish, wiki) & _INTERESTING_TAGS), "spicy": dish.get("spicy", 0)}


_INTERESTING_TAGS = {"high_protein", "lean", "low_fat", "fat_loss", "budget", "quick", "one_pot", "soup", "steamed",
                     "soft", "stomach_friendly", "child_friendly", "pregnancy_friendly", "elderly_friendly",
                     "fatty_meat", "high_fat", "processed", "spicy", "high_sugar", "whole_grain", "low_gi",
                     "pork", "beef", "lamb", "poultry", "fish", "seafood", "shellfish", "soy", "egg", "milk",
                     "iron", "calcium", "high_oil"}
