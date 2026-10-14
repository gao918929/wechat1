from app.services.nl import cn_number, parse_card_command, parse_inventory_command, parse_plan_instruction

DEMO_ZH = "我在减脂，身高175cm体重72kg，宿舍4个人，这周伙食预算每人80元，我不吃辣不吃海鲜，冰箱里有番茄、鸡蛋和快过期的鸡胸肉，帮我们规划一周减脂晚餐"
DEMO_EN = ("I'm trying to lose body fat. I'm 175 cm tall and weigh 72 kg. There are four people in our dormitory, and our "
           "food budget this week is CNY 80 per person. I don't eat spicy food or seafood. We have tomatoes, eggs, and "
           "chicken breast that's about to expire in the refrigerator. Please plan a week's fat-loss dinners for us.")


def test_wiki_loads_everything(wiki):
    assert len(wiki.ingredients) >= 70
    assert len(wiki.dishes) >= 45
    assert {"fat_loss", "pregnancy", "halal", "vegetarian", "child_growth", "chronic_control"} <= set(wiki.diet_models)
    for dish in wiki.dishes.values():
        for name, grams in dish.ingredients:
            assert name in wiki.ingredients, f"{dish.name}: unknown ingredient {name}"
            assert grams > 0
    assert wiki.shelf["leafy"].near_expiry_days == 1
    assert wiki.reference_objects["egg"].size_cm == 4.5
    assert wiki.meal_shares["dinner"] == 0.3


def test_resolve_aliases(wiki):
    assert wiki.resolve("西红柿") == "番茄"
    assert wiki.resolve("chicken breast") == "鸡胸肉"
    assert wiki.resolve("白菜") == "大白菜"
    assert wiki.ingredient("蚝油").allergens >= {"seafood"}


def test_cn_numbers():
    assert cn_number("两") == 2
    assert cn_number("十二") == 12
    assert cn_number("二十") == 20
    assert cn_number("半") == 0.5
    assert cn_number("一半") is not None


def test_inventory_chat_parse(wiki):
    p = parse_inventory_command("冰箱里还有两个鸡蛋和半颗白菜", wiki)
    assert p["intent"] == "set"
    assert {"name": "鸡蛋", "quantity": 2.0} in [{k: i[k] for k in ("name", "quantity")} for i in p["items"]]
    assert p["items"][1]["name"] == "大白菜" and p["items"][1]["quantity"] == 0.5
    p = parse_inventory_command("今天用了2个鸡蛋", wiki)
    assert p["intent"] == "consume" and p["items"][0]["quantity"] == 2
    p = parse_inventory_command("买了一斤猪里脊", wiki)
    assert p["intent"] == "add" and p["items"][0]["weight_g"] == 500


def test_card_chat_parse(wiki):
    assert parse_card_command("把白菜改成400克", wiki) == [{"op": "set", "name": "大白菜", "weight_g": 400.0}]
    assert parse_card_command("这不是娃娃菜，是小白菜", wiki) == [{"op": "rename", "from": "娃娃菜", "to": "小白菜"}]
    assert parse_card_command("删掉黄瓜", wiki) == [{"op": "remove", "name": "黄瓜"}]


def test_plan_instruction_chinese(wiki):
    p = parse_plan_instruction(DEMO_ZH, wiki)
    assert p["height_cm"] == 175 and p["weight_kg"] == 72 and p["people"] == 4
    assert p["budget_mode"] == "per_person" and p["budget_amount"] == 80
    assert p["goal"] == "fat_loss" and p["days"] == 7 and p["meals"] == ["dinner"]
    assert set(p["avoid"]) == {"spicy", "seafood"}
    mentions = {m["name"]: m["near_expiry"] for m in p["inventory_mentions"]}
    assert mentions == {"番茄": False, "鸡蛋": False, "鸡胸肉": True}


def test_plan_instruction_english(wiki):
    p = parse_plan_instruction(DEMO_EN, wiki)
    assert p["people"] == 4 and p["budget_amount"] == 80 and p["budget_mode"] == "per_person"
    assert set(p["avoid"]) == {"spicy", "seafood"}
    assert {m["name"]: m["near_expiry"] for m in p["inventory_mentions"]}["鸡胸肉"] is True
    assert p["meals"] == ["dinner"] and p["goal"] == "fat_loss"
