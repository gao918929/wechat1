"""Rule-based natural-language parsing.

Used for conversational edits ("冰箱里还有两个鸡蛋和半颗白菜", "把白菜改成400克") and for
extracting constraints from a planning instruction. When DeepSeek is configured the LLM parses
first and these rules are the fallback; with no API key they are the only parser.
"""
from __future__ import annotations

import re

from ..wiki import Wiki

CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "俩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "半": 0.5}
EN_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
NUM_RE = r"[\d.]+|[零一二两俩三四五六七八九十半]+"
PIECE_UNITS = "个|颗|根|只|棵|盒|袋|把|块|条|片|瓶|份|斤|公斤|千克|kg|KG|Kg|克|g|G"

# Free-text avoidance keywords → constraint labels (wiki tags / allergen keys)
AVOID_KEYWORDS = [
    ("辣", "spicy"), ("spicy", "spicy"), ("海鲜", "seafood"), ("seafood", "seafood"), ("水产", "seafood"),
    ("肥肉", "fatty_meat"), ("fatty meat", "fatty_meat"), ("猪肉", "pork"), ("pork", "pork"),
    ("牛肉", "beef"), ("beef", "beef"), ("羊肉", "lamb"), ("lamb", "lamb"), ("鱼", "fish"), ("fish", "fish"),
    ("虾", "shellfish"), ("蟹", "shellfish"), ("shellfish", "shellfish"), ("内脏", "organ"), ("香菜", "cilantro"),
    ("cilantro", "cilantro"), ("花生", "peanut"), ("peanut", "peanut"), ("坚果", "nut"), ("鸡蛋", "egg"),
    ("蛋", "egg"), ("牛奶", "milk"), ("乳", "milk"), ("dairy", "milk"), ("芝麻", "sesame"), ("大豆", "soy"),
    ("麸质", "wheat"), ("小麦", "wheat"), ("甜", "high_sugar"), ("油炸", "fried"), ("芒果", "mango"),
]
GROUP_KEYWORDS = [
    (r"怀孕|孕妇|孕期|哺乳|pregnan", "pregnancy"), (r"宝宝|孩子|儿童|小朋友|child|kid", "child_growth"),
    (r"高血压|高血糖|高血脂|糖尿病|控糖|三高|血糖|diabet|hypertens", "chronic_control"),
    (r"素食|吃素|vegetarian", "vegetarian"), (r"清真|halal", "halal"), (r"养胃|胃不好|清淡|stomach", "light_stomach"),
    (r"省钱|穷|budget meal", "budget_dormitory"),
]


def cn_number(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    if s.lower() in EN_NUM:
        return float(EN_NUM[s.lower()])
    if s.endswith("半") and len(s) > 1:
        base = cn_number(s[:-1])
        return None if base is None else base + 0.5
    if "十" in s:
        a, _, b = s.partition("十")
        tens = CN_NUM.get(a, 1) if a else 1
        ones = CN_NUM.get(b, 0) if b else 0
        return float(tens * 10 + ones)
    total = 0.0
    for ch in s:
        if ch not in CN_NUM:
            return None
        total = total * 10 + CN_NUM[ch] if CN_NUM[ch] >= 1 else total + CN_NUM[ch]
    return total


def _to_amount(num: float, unit: str | None) -> dict:
    unit = (unit or "").lower()
    if unit in ("克", "g"):
        return {"weight_g": num}
    if unit in ("斤",):
        return {"weight_g": num * 500}
    if unit in ("公斤", "千克", "kg"):
        return {"weight_g": num * 1000}
    return {"quantity": num}


def _amount_near(text: str, start: int, end: int) -> dict:
    """Find "两个" before or "400克" after an ingredient mention."""
    before = re.split(r"[，,。；;、和与跟及还有用了吃了]", text[max(0, start - 8):start])[-1]
    m = re.search(rf"({NUM_RE})\s*({PIECE_UNITS})?\s*$", before)
    if m and cn_number(m.group(1)) is not None:
        return _to_amount(cn_number(m.group(1)), m.group(2))
    after = text[end:end + 10]
    m = re.match(rf"^\s*[:：]?\s*({NUM_RE})\s*({PIECE_UNITS})?", after)
    if m and cn_number(m.group(1)) is not None:
        return _to_amount(cn_number(m.group(1)), m.group(2))
    return {}


def _intent(text: str) -> str:
    if re.search(r"扔了|扔掉|坏了|丢了|删掉|删除|没有了|用完了|吃完了|移除", text):
        return "remove"
    if re.search(r"用了|吃了|用掉|吃掉|消耗|做了|煮了|炒了|used|ate", text):
        return "consume"
    if re.search(r"还有|还剩|剩下|剩了|现在有|冰箱里有|有\s*$", text):
        return "set"
    return "add"


def parse_inventory_command(text: str, wiki: Wiki) -> dict:
    """Inventory edits from chat. Returns {intent, items:[{name, quantity?, weight_g?}]}."""
    intent = _intent(text)
    items = []
    for canon, s, e in wiki.find_in_text(text):
        item = {"name": canon, "mention": text[s:e]}
        item.update(_amount_near(text, s, e))
        items.append(item)
    return {"intent": intent if items else "unknown", "items": items}


def parse_card_command(text: str, wiki: Wiki) -> list[dict]:
    """Edits to a recognition item-list card. Returns ops: rename / set / remove / add."""
    ops: list[dict] = []
    t = text.strip()
    m = re.search(r"(?:这|这个)?不是(.+?)[，,。\s]*(?:而)?是(.+?)[。！!]?$", t)
    if m:
        ops.append({"op": "rename", "from": m.group(1).strip(), "to": wiki.resolve(m.group(2).strip()) or m.group(2).strip()})
        return ops
    for m in re.finditer(rf"把?([^，,。把]+?)(?:改成|改为|换成|是)\s*({NUM_RE})\s*({PIECE_UNITS})", t):
        target = m.group(1).strip()
        num = cn_number(m.group(2))
        if num is not None:
            ops.append({"op": "set", "name": wiki.resolve(target) or target, **_to_amount(num, m.group(3))})
    if ops:
        return ops
    m = re.search(r"(?:删掉|去掉|删除|不要|移除)(.+)", t)
    if m:
        for canon, _, _ in wiki.find_in_text(m.group(1)) or [(m.group(1).strip(), 0, 0)]:
            ops.append({"op": "remove", "name": canon})
        return ops
    m = re.search(r"(?:加上|添加|还有|再加|漏了)(.+)", t)
    if m:
        segment = m.group(1)
        for canon, s, e in wiki.find_in_text(segment):
            ops.append({"op": "add", "name": canon, **_amount_near(segment, s, e)})
    return ops


KNOWN_LABELS = {label for _, label in AVOID_KEYWORDS} | {"mollusk", "alcohol", "processed", "high_fat", "raw_risk"}


def normalize_avoid(token: str, wiki: Wiki) -> str | None:
    token = token.strip().strip("的了").strip()
    if not token:
        return None
    low = token.lower()
    if low in KNOWN_LABELS:
        return low
    for kw, label in AVOID_KEYWORDS:
        if kw in low and (len(kw) > 1 or len(token) <= 2):
            return label
    return wiki.resolve(token)


def parse_plan_instruction(text: str, wiki: Wiki) -> dict:
    """Extract planning constraints from a natural-language instruction (Chinese or English)."""
    out: dict = {"avoid": [], "allergens": [], "dietary_groups": [], "inventory_mentions": []}
    low = text.lower()

    m = re.search(r"(\d{3}(?:\.\d+)?)\s*(?:cm|厘米|公分)", low) or re.search(r"身高\s*(\d+(?:\.\d+)?)", text)
    if m:
        h = float(m.group(1))
        out["height_cm"] = h * 100 if h < 3 else h
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤|千克)", low)
    if m:
        out["weight_kg"] = float(m.group(1))
    else:
        m = re.search(r"体重\s*(\d{2,3}(?:\.\d+)?)\s*斤", text)
        if m:
            out["weight_kg"] = float(m.group(1)) / 2
    m = re.search(r"(\d+|[一二两三四五六七八九十]+)\s*(?:个人|人|位|口人)", text) or re.search(
        r"(\d+|one|two|three|four|five|six|seven|eight)\s+(?:people|persons|of us)", low)
    if m:
        out["people"] = int(cn_number(m.group(1)) or 1)

    m = (re.search(r"(?:每人|人均|一人|每个人)[^\d]{0,8}(\d+(?:\.\d+)?)", text)
         or re.search(r"预算[^\d]{0,10}(\d+(?:\.\d+)?)\s*(?:元|块)?[^，,。]{0,4}(每人|人均|/人|一人)", text))
    if m:
        out["budget_mode"], out["budget_amount"] = "per_person", float(m.group(1))
    else:
        m = re.search(r"(?:cny|rmb|¥|￥)\s*(\d+(?:\.\d+)?)\s*per\s*person", low) or re.search(
            r"(\d+(?:\.\d+)?)\s*(?:cny|yuan|元)?\s*per\s*person", low)
        if m:
            out["budget_mode"], out["budget_amount"] = "per_person", float(m.group(1))
        else:
            m = re.search(r"预算[^\d]{0,10}(\d+(?:\.\d+)?)", text) or re.search(r"budget[^\d]{0,20}(\d+(?:\.\d+)?)", low)
            if m:
                out["budget_mode"], out["budget_amount"] = "total", float(m.group(1))

    if re.search(r"减脂|减肥|瘦身|刷脂|lose (?:body )?fat|lose weight|fat[- ]loss", low):
        out["goal"] = "fat_loss"
    elif re.search(r"增肌|长肌肉|muscle", low):
        out["goal"] = "muscle_gain"
    elif re.search(r"养胃|胃不好", text):
        out["goal"] = "stomach"
    for pattern, gid in GROUP_KEYWORDS:
        if re.search(pattern, low) and gid not in out["dietary_groups"]:
            out["dietary_groups"].append(gid)

    for m in re.finditer(r"(?:不吃|不能吃|不爱吃|忌口|不要)([^，,。；;！!]+)", text):
        for tok in re.split(r"[、和与跟及/,，]|不吃|也不吃", m.group(1)):
            label = normalize_avoid(tok, wiki)
            if label and label not in out["avoid"]:
                out["avoid"].append(label)
    for m in re.finditer(r"(?:don'?t|do not|never|can'?t) eat ([^.;,]+)", low):
        for tok in re.split(r"\bor\b|\band\b|/", m.group(1)):
            label = normalize_avoid(re.sub(r"\bfoods?\b", "", tok), wiki)
            if label and label not in out["avoid"]:
                out["avoid"].append(label)
    for m in re.finditer(r"对?([^，,。；;对]{1,8}?)过敏", text):
        label = normalize_avoid(m.group(1), wiki)
        if label and label not in out["allergens"]:
            out["allergens"].append(label)
    for m in re.finditer(r"allergic to ([a-z ]+)", low):
        label = normalize_avoid(m.group(1), wiki)
        if label and label not in out["allergens"]:
            out["allergens"].append(label)

    seg = re.search(r"(?:冰箱里?|家里|宿舍里?|库存)?(?:还)?有(.+?)(?:[。；;！!]|帮|请|$)", text)
    if seg:
        segment = seg.group(1)
        for canon, s, e in wiki.find_in_text(segment):
            before = re.split(r"[、，,和与及跟]", segment[max(0, s - 10):s])[-1]
            after = re.split(r"[、，,和与及跟]", segment[e:e + 10])[0]
            mention = {"name": canon,
                       "near_expiry": bool(re.search(r"快过期|临期|要过期|快坏|不新鲜", before + "|" + after))}
            mention.update(_amount_near(segment, s, e))
            out["inventory_mentions"].append(mention)
    for name_en, canon in (("tomato", "番茄"), ("egg", "鸡蛋"), ("chicken breast", "鸡胸肉")):
        if re.search(rf"(?:we have|there (?:is|are)|fridge)[^.]*\b{name_en}", low) and not any(
                i["name"] == canon for i in out["inventory_mentions"]):
            near = bool(re.search(rf"{name_en}[^.,]*(?:about to expire|expir)", low))
            out["inventory_mentions"].append({"name": canon, "near_expiry": near})

    if re.search(r"一周|一星期|本周|这周|7\s*天|七天|a week|week", low):
        out["days"] = 7
    m = re.search(r"(\d+|[一二两三四五六七])\s*天", text)
    if m:
        out["days"] = int(cn_number(m.group(1)) or 7)
    meals = []
    for pattern, meal in ((r"早餐|早饭|breakfast", "breakfast"), (r"午餐|午饭|中饭|lunch", "lunch"),
                          (r"晚餐|晚饭|dinner|supper", "dinner")):
        if re.search(pattern, low):
            meals.append(meal)
    if re.search(r"三餐|一日三餐|all meals", low):
        meals = ["breakfast", "lunch", "dinner"]
    if meals:
        out["meals"] = meals
    return out
