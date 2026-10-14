from datetime import date, datetime, timedelta

from app.models import InventoryItem
from app.services.estimation import estimate_weight, update_calibration
from app.services.inventory import freshness
from app.services.nutrition import daily_targets, health_score, nutrition_of
from app.services.pricing import complete_item, unit_price
from app.services.shopping import build_shopping, shopping_text


def test_fat_loss_targets(wiki):
    t = daily_targets({"sex": "male", "age": 21, "height_cm": 175, "weight_kg": 72, "goal": "fat_loss"}, wiki)
    # Mifflin: 10*72 + 6.25*175 - 5*21 + 5 = 1713.75; ×1.375 ×0.8 ≈ 1885
    assert 1850 <= t["kcal"] <= 1920
    assert t["protein_g"] == round(1.6 * 72)
    assert t["estimated"] is False


def test_pregnancy_overrides_deficit(wiki):
    t = daily_targets({"sex": "female", "age": 28, "height_cm": 162, "weight_kg": 58, "goal": "fat_loss",
                       "dietary_groups": ["pregnancy"]}, wiki)
    assert any("孕期" in n for n in t["notes"])
    base = daily_targets({"sex": "female", "age": 28, "height_cm": 162, "weight_kg": 58}, wiki)
    assert t["kcal"] == base["kcal"] + 300


def test_default_targets_when_no_metrics(wiki):
    t = daily_targets({"sex": "female"}, wiki)
    assert t["kcal"] == 1700 and t["estimated"] is True


def test_nutrition_and_score(wiki):
    n = nutrition_of([("鸡蛋", 100), ("番茄", 150), ("植物油", 8), ("不存在的东西", 10)], wiki)
    assert round(n["kcal"]) == round(139 + 22.5 + 71.9)
    assert n["unknown"] == ["不存在的东西"]
    daily = daily_targets({"sex": "male"}, wiki)
    good = health_score({"kcal": daily["kcal"], "protein": daily["protein_g"], "fat": daily["kcal"] * 0.25 / 9,
                         "salt_g": 4, "vegetable_g": 400}, daily)
    bad = health_score({"kcal": daily["kcal"] * 1.6, "protein": 20, "fat": 150, "salt_g": 12, "vegetable_g": 50}, daily)
    assert good["score"] == 100 and bad["score"] < 40 and bad["reasons"]


def test_unit_price_completion_tiers(wiki):
    a = complete_item({"name": "猪里脊", "amount": 16.0, "weight_g": 500}, wiki)
    assert a["unit_price"] == 32.0 and not a["estimated"]
    b = complete_item({"name": "鸡蛋", "amount": 6.0, "quantity": 10}, wiki)
    assert b["weight_g"] == 500 and b["unit_price"] == 12.0 and b["estimated"]
    c = complete_item({"name": "番茄"}, wiki)
    assert c["unit_price"] == 8.0 and c["estimated"]
    hist = unit_price("番茄", {"番茄": 5.5}, wiki)
    assert hist == {"unit_price": 5.5, "estimated": False, "source": "history"}


def test_reference_object_estimation(wiki):
    # cabbage 4x the egg's pixel size → 18 cm vs 20 cm reference head → 2000 * 0.9^3 ≈ 1458 g
    est = estimate_weight({"name": "大白菜", "count": 1, "size_px": 400, "confidence": 0.9}, wiki,
                          {"key": "egg", "size_px": 100})
    assert 1400 <= est["weight_g"] <= 1500 and est["range_pct"] == 15 and "估算" in est["text"]
    twin = update_calibration({}, "大白菜", est["weight_g"], est["weight_g"] * 1.2)
    est2 = estimate_weight({"name": "大白菜", "count": 1, "size_px": 400, "confidence": 0.9}, wiki,
                           {"key": "egg", "size_px": 100}, twin)
    assert est2["weight_g"] > est["weight_g"] and "校准" in est2["method"]
    none = estimate_weight({"name": "豆芽", "count": 1}, wiki)
    assert none["weight_g"] is None and none["text"] == "已识别食材，需补充重量"


def test_freshness_levels(wiki):
    today = date.today()
    leafy = InventoryItem(name="菠菜", added_at=datetime.now(), purchase_date=today - timedelta(days=2), freshness="fresh")
    assert freshness(leafy, wiki, today)["level"] == "near_expiry"
    old = InventoryItem(name="菠菜", added_at=datetime.now(), purchase_date=today - timedelta(days=5), freshness="fresh")
    assert freshness(old, wiki, today)["level"] == "expired"
    eggs = InventoryItem(name="鸡蛋", added_at=datetime.now(), purchase_date=today, freshness="not_fresh")
    assert freshness(eggs, wiki, today)["level"] == "not_fresh"  # visual beats time


def test_shopping_list_subtracts_inventory(wiki):
    need = {"鸡蛋": 600, "番茄": 300, "盐": 10, "牛肉": 400}
    inv = [{"name": "鸡蛋", "grams": 600}, {"name": "番茄", "grams": 100}]
    s = build_shopping(need, inv, {}, wiki, people=4, budget_total=20)
    names = [i["name"] for sec in s["sections"] for i in sec["items"]]
    assert "鸡蛋" not in names and "番茄" in names and "牛肉" in names
    assert s["pantry"][0]["name"] == "盐"
    assert s["over_budget"] is True and s["per_person_cost"] == round(s["total_cost"] / 4, 2)
    text = shopping_text(s, "测试")
    assert "超出预算" in text and "常备调料检查：盐" in text
