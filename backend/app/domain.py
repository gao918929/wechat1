"""Deterministic inventory, price, nutrition, safety and budget rules.
AI suggestions never bypass these checks. Amounts are edible raw grams.
"""
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException
from .schemas import PlanBundle, Profile
from .store import digest, packed

DATA = Path(__file__).resolve().parents[1] / "data"
DISCLAIMER = "本方案为通用膳食参考，不构成医疗诊断依据。慢病、孕哺期及儿童请遵医嘱；过敏者还需核对包装与交叉接触风险。"
SPECIAL = {"pregnant", "lactating", "chronic", "child"}
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "calcium_mg", "iron_mg", "sodium_mg", "vitamin_c_mg")


def catalog():
    foods = {f["id"]: f for f in json.loads((DATA / "ingredients.json").read_text(encoding="utf-8"))}
    overrides = DATA.parents[1] / "data/nutrition_overrides.json"
    if overrides.exists():
        for food in json.loads(overrides.read_text(encoding="utf-8")):
            if food["id"] in foods:
                food["allergens"] = sorted(set(food["allergens"]) | set(foods[food["id"]]["allergens"]))
            foods[food["id"]] = food
    return foods


def known(food_id):
    food = catalog().get(food_id)
    if not food:
        raise HTTPException(422, f"Unknown ingredient: {food_id}")
    return food


def nutrition(items, foods=None):
    foods = foods or catalog()
    totals = {n: 0.0 for n in NUTRIENTS}
    missing = set()
    for item in items:
        food = foods.get(item["ingredient_id"])
        if not food:
            raise HTTPException(422, "Ingredient is not in the verified catalog")
        for key in NUTRIENTS:
            value = food["per_100g"].get(key)
            if value is None:
                missing.add(key)
            else:
                totals[key] += value * item["grams"] / 100
    return {key: None if key in missing else round(value, 2) for key, value in totals.items()}


def target_for(profile):
    p = Profile.model_validate(profile)
    if p.meal_target:
        return {**p.meal_target.model_dump(), "source": "User-confirmed per-meal targets; not independently medically verified"}
    standards = DATA.parents[1] / "data/target_standards.json"
    if standards.exists() and p.age:
        for row in json.loads(standards.read_text(encoding="utf-8")):
            # Exact tags prevent a generic adult standard from applying to a special group.
            if row["age_min"] <= p.age <= row["age_max"] and row["sex"] in ("any", p.sex) and set(row.get("tags", [])) == set(p.tags):
                return {**row["meal_target"], "source": row["source"], "source_url": row["source_url"]}
    # Do not silently apply adult formulae to pregnant/lactating/young/chronic users.
    if SPECIAL.intersection(p.tags) or not p.age or p.age < 18:
        raise HTTPException(422, "Set confirmed per-meal nutrition targets; adult estimation cannot be used for this profile")
    if not p.height_cm or not p.weight_kg or p.sex == "unspecified":
        raise HTTPException(422, "Complete age, height, weight and sex, or enter explicit per-meal targets")
    basal = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * p.age + (5 if p.sex == "male" else -161)
    # Reference calculation only: fixed light-activity assumption, one dinner = 35%.
    # No automatic caloric deficit prescribed from a fat-loss tag.
    meal_kcal = basal * 1.4 * .35
    return {"kcal_min": round(meal_kcal * .8), "kcal_max": round(meal_kcal * 1.2),
            "protein_min": round(meal_kcal * .15 / 4), "protein_max": round(meal_kcal * .30 / 4),
            "carbs_min": round(meal_kcal * .40 / 4), "carbs_max": round(meal_kcal * .65 / 4),
            "fat_min": round(meal_kcal * .15 / 9), "fat_max": round(meal_kcal * .35 / 9),
            "source": "Estimated adult reference: Mifflin–St Jeor RMR × 1.4 × 35%; not a DRIs prescription"}


def freshness(item, today=None):
    today = today or date.today()
    left = (date.fromisoformat(item["expires_on"]) - today).days
    threshold = known(item["ingredient_id"])["near_expiry_days"]
    if item["freshness"] == "not_fresh":
        return "not_fresh"
    if left < 0:
        return "expired"
    return "near_expiry" if left <= threshold else "normal"


def price_map(store, db, group):
    result = {}
    # Reverse chronological items: the first exact receipt price wins.
    for row in store.items(db, "price", group):
        key = row["ingredient_id"]
        if key not in result or (result[key]["estimated"] and not row["estimated"]):
            result[key] = {"cents_per_kg": row["cents_per_kg"], "estimated": row["estimated"], "source": row["source"]}
    return result


def consume(store, db, group, owner, items):
    # Aggregate duplicate lines before checking, then change all rows in one transaction.
    amounts = defaultdict(float)
    for item in items:
        amounts[item["inventory_id"]] += item["grams"]
    for key, grams in amounts.items():
        row = store.get(db, key, "inventory")
        if row["group_id"] != group:
            raise HTTPException(403, "Inventory belongs to a different group")
        if grams > row["grams"] + 1e-6:
            raise HTTPException(409, f"Insufficient inventory for {known(row['ingredient_id'])['name']}; no stock was deducted")
        if freshness(row) in ("expired", "not_fresh"):
            raise HTTPException(422, "Do not consume expired or visibly spoiled inventory; discard it instead")
        row["grams"] = round(max(0, row["grams"] - grams), 3)
        store.put(db, "inventory", group, row["owner_id"], row, key, row["version"])
    store.emit(db, group, owner, "inventory_changed", {})


def snapshot(store, db, group, user, request):
    diners = []
    if len(set(request["diners"])) != len(request["diners"]):
        raise HTTPException(422, "Duplicate diners are not allowed")
    if date.fromisoformat(request["start_date"]) < date.today():
        raise HTTPException(422, "Plan start date must not be in the past")
    for member in request["diners"]:
        store.member(db, group, member)
        row = db.execute("SELECT id,name,profile FROM users WHERE id=?", (member,)).fetchone()
        profile = json.loads(row["profile"])
        target = target_for(profile)
        # Physical measurements and personal twins are never placed in group prompts.
        safe_profile = {k: v for k, v in Profile.model_validate(profile).model_dump().items()
                        if k in {"tags", "allergens", "forbidden_ingredients", "dislikes", "likes", "goal"}}
        diners.append({"id": row["id"], "profile": safe_profile, "target": target})
    stocks = [i for i in store.items(db, "inventory", group) if i["grams"] > 0]
    prices = price_map(store, db, group)
    foods = catalog()
    eligible = set(prices) | {i["ingredient_id"] for i in stocks if freshness(i) not in ("expired", "not_fresh")}
    if not eligible:
        raise HTTPException(422, "Add inventory or reference prices before generating a plan")
    feedback = [f for f in store.items(db, "feedback", group) if f["shared"] or f["owner_id"] == user][:60]
    meals = store.items(db, "meal", group, user)[:14]
    return {"request": request, "diners": diners, "inventory": stocks,
            "foods": {k: foods[k] for k in sorted(eligible) if k in foods}, "prices": prices,
            "feedback": [{k:v for k,v in f.items() if k in {"action", "rating", "mode", "text"}} for f in feedback],
            "recent_intake": [{"eaten_on": m["eaten_on"], "nutrition": m["nutrition"]} for m in meals],
            "disclaimer": DISCLAIMER}


def blocked(food, profile):
    if set(food["allergens"]) & set(profile.get("allergens", [])):
        return True
    if food["id"] in profile.get("forbidden_ingredients", []):
        return True
    if "vegetarian" in profile.get("tags", []) and not food["vegetarian"]:
        return True
    if "halal" in profile.get("tags", []) and not food["halal_compatible"]:
        return True
    return False


def validate_plan(raw, context):
    """Returns (validated enriched plan, errors). Never trusts AI nutrient/price totals."""
    try:
        bundle = PlanBundle.model_validate(raw).model_dump(mode="json")
    except Exception as exc:
        return None, [{"layer": "schema", "message": "Invalid plan schema", "detail": str(exc)[:1800]}]
    req, diners, foods = context["request"], context["diners"], context["foods"]
    ids = {d["id"] for d in diners}
    total_budget = req["budget_cents"] * (len(ids) if req["budget_mode"] == "per_person" else 1)
    expected_dates = [(date.fromisoformat(req["start_date"]) + timedelta(days=i)).isoformat() for i in range(req["days"])]
    modes = [v["mode"] for v in bundle["variants"]]
    errors = []
    if len(modes) != len(set(modes)) or "balanced" not in modes:
        errors.append({"layer": "schema", "message": "Unique modes including balanced are required"})
    special = any(SPECIAL.intersection(d["profile"].get("tags", [])) for d in diners)
    soft_conflict = len({tuple(sorted(d["profile"].get("dislikes", []))) for d in diners}) > 1
    split_allowed = special or soft_conflict
    for variant in bundle["variants"]:
        mode = variant["mode"]
        def error(layer, message):
            errors.append({"layer": layer, "mode": mode, "message": message})
        if [d["date"] for d in variant["days"]] != expected_dates:
            error("schema", "Dates must exactly match the requested period in order")
        lots = [{**i, "remaining": i["grams"]} for i in context["inventory"] if i["freshness"] != "not_fresh"]
        lots.sort(key=lambda i: (i["expires_on"], i["created_at"]))
        purchases = defaultdict(float)
        per_diner = {d["id"]: {n: 0 for n in NUTRIENTS} for d in diners}
        for day in variant["days"]:
            day_totals = {d["id"]: {n: 0.0 for n in NUTRIENTS} for d in diners}
            for dish in day["dishes"]:
                recipients = dish["suitable_for"] or list(ids)
                if not set(recipients) <= ids or len(recipients) != len(set(recipients)):
                    error("health", "Invalid or duplicate recipient IDs")
                    continue
                if not split_allowed and set(recipients) != ids:
                    error("health", "Ordinary groups must receive everyone-compatible dishes")
                if not split_allowed:
                    dish["suitable_for"] = []
                valid_items = []
                for portion in dish["ingredients"]:
                    fid = portion["ingredient_id"]
                    food = foods.get(fid)
                    if not food:
                        error("inventory", f"Unknown/unavailable ingredient {fid}")
                        continue
                    # Hard allergens/contraindications are excluded globally, even in split meals.
                    if any(blocked(food, d["profile"]) for d in diners):
                        error("health", f"Hard exclusion: {fid}")
                    if not req["override_soft"]:
                        for d in diners:
                            dislikes = d["profile"].get("dislikes", [])
                            if d["id"] in recipients and any(x.lower() in (fid.lower(), food["name"].lower(), food["name_en"].lower()) for x in dislikes):
                                error("health", f"Unapproved soft-constraint override: {fid}")
                    left = portion["grams"]
                    for lot in lots:
                        if lot["ingredient_id"] == fid and lot["expires_on"] >= day["date"]:
                            used = min(left, lot["remaining"])
                            lot["remaining"] -= used
                            left -= used
                    if left > 1e-6:
                        purchases[fid] += left
                    valid_items.append(portion)
                if len(valid_items) != len(dish["ingredients"]):
                    continue
                nutrients = nutrition(valid_items, foods)
                dish["nutrition_total"] = nutrients
                # Also reject prohibited catalog aliases hidden in free-text instructions.
                forbidden_aliases = [alias.lower() for f in catalog().values()
                                     if any(blocked(f, d["profile"]) for d in diners)
                                     for alias in [f["name"], *f.get("aliases", [])] if len(alias) >= 2]
                step_text = " ".join(dish["steps"]).lower()
                if any(alias in step_text for alias in forbidden_aliases):
                    error("health", "Preparation instructions mention a prohibited ingredient")
                for person in recipients:
                    for key, amount in nutrients.items():
                        if amount is None:
                            day_totals[person][key] = None
                        elif day_totals[person][key] is not None:
                            day_totals[person][key] += amount / len(recipients)
            for d in diners:
                totals = day_totals[d["id"]]
                for key in ("kcal", "protein", "carbs", "fat"):
                    value, target = totals[key], d["target"]
                    if value is None or not target[key + "_min"] <= value <= target[key + "_max"]:
                        error("health", f"{day['date']} {d['id']} {key} outside target range")
                for key, value in totals.items():
                    if value is None:
                        per_diner[d["id"]][key] = None
                    elif per_diner[d["id"]][key] is not None:
                        per_diner[d["id"]][key] += value
            day["nutrition_per_person"] = {k:{n:None if v is None else round(v,2) for n,v in ns.items()} for k,ns in day_totals.items()}
        shopping, cost = [], 0
        for fid, grams in sorted(purchases.items(), key=lambda pair: foods[pair[0]]["category"]):
            price = context["prices"].get(fid)
            if not price:
                error("budget", f"Missing purchase price for {fid}; add a reference price")
                continue
            cents = math.ceil(grams * price["cents_per_kg"] / 1000)
            cost += cents
            shopping.append({"ingredient_id": fid, "name": foods[fid]["name"], "category": foods[fid]["category"],
                             "grams": round(grams,2), "cents": cents, **price})
        if cost > total_budget and mode != "health":
            error("budget", f"Shopping cost {cost} exceeds budget {total_budget}")
        remaining_near = [i["ingredient_id"] for i in lots if i["remaining"] > 1 and i["expires_on"] <= expected_dates[-1]
                          and i["expires_on"] >= expected_dates[0]]
        variant["warnings"] = []
        if cost > total_budget:
            variant["warnings"].append("Health-first option exceeds your budget; explicit selection is required.")
        if remaining_near:
            variant["warnings"].append("Some near-expiry stock remains unused: " + ", ".join(sorted(set(remaining_near))))
        variant.update(shopping=shopping, cost_cents=cost, budget_cents=total_budget,
                       per_person_cents=math.ceil(cost/len(ids)), nutrition_totals=per_diner,
                       nutrition_is_estimate=True, data_sources=list({f["source"] for f in foods.values()}),
                       disclaimer=DISCLAIMER, split_mode=split_allowed)
    if errors:
        return None, errors
    # Selection history ranks alternatives, but does not bypass any validation.
    counts = defaultdict(int)
    for feedback in context.get("feedback", []):
        if feedback.get("action") == "select":
            counts[feedback.get("mode")] += 1
    bundle["variants"].sort(key=lambda v: (-counts[v["mode"]], v["mode"] != "balanced"))
    return bundle, []
