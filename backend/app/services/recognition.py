"""Image recognition (DeepSeek multimodal → structured JSON) and item-list-card post-processing."""
from __future__ import annotations

import copy

from ..llm import LLMClient, LLMError, LLMUnavailable, image_data_url
from ..wiki import Wiki
from .estimation import estimate_weight
from .nutrition import nutrition_of
from .pricing import complete_item

LOW_CONFIDENCE = 0.6

INGREDIENT_PROMPT = """你是 MealAgent 的食材识别模块。识别图片中的每种食材及数量，并检测图中的参照物
（egg 鸡蛋 / bottle 矿泉水瓶 / plate 餐盘 / chopsticks 筷子 / coin 一元硬币 / phone 手机）。
- size_px：该食材单个个体主尺寸（直径或长度）的像素值；reference.size_px 同理。
- freshness：fresh 新鲜 / wilted 萎蔫 / discolored 变色发黑 / not_fresh 不新鲜（肉色异常等）。
- 只有包装上能清楚读出净含量时才填写 weight_g，否则不要猜重量。
输出 JSON：{"items":[{"name":"中文食材名","count":1,"size_px":120,"confidence":0.9,"freshness":"fresh","weight_g":null}],
"reference":{"key":"egg","size_px":60} 或 null}"""

RECEIPT_PROMPT = """你是 MealAgent 的小票/价签识别模块。识别超市小票、菜市场收据或称重商品价签。
- 单价统一换算为 元/kg（价签若是 元/500g 需 ×2）；重量统一为克；amount 为该行实付金额。
- 识别不到的字段填 null，不要编造；手写只有总价时 items 为空数组。
输出 JSON：{"kind":"receipt|label","merchant":"","date":"YYYY-MM-DD 或 null","total":实付总额,
"items":[{"name":"","quantity":null,"weight_g":null,"unit_price":null,"amount":null}]}"""

MEAL_PROMPT = """你是 MealAgent 的餐后拍照复盘模块。判断就餐场景：home 自己做的家常饭 / out 外食或外卖（餐盒、包装、餐厅餐具等线索）。
识别每道菜及其主要食材与估计克数（整张照片中的总量），portion 为图中这道菜大约够几人份。
输出 JSON：{"context":"home|out","dishes":[{"name":"菜名","portion":1,"ingredients":[{"name":"食材","grams":100}]}],"confidence":0.8}"""


def _visual_flag(freshness: str | None) -> str:
    return "not_fresh" if freshness in ("wilted", "discolored", "not_fresh") else "fresh"


def ingredient_card(raw: dict, wiki: Wiki, twin_data: dict | None) -> dict:
    items = []
    ref = raw.get("reference") or None
    for idx, it in enumerate(raw.get("items") or []):
        ing = wiki.ingredient(str(it.get("name", "")))
        conf = float(it.get("confidence") or 0.7)
        row = {"id": idx, "name": ing.name if ing else it.get("name", ""), "recognized_as": it.get("name", ""),
               "canonical": ing.name if ing else None, "quantity": it.get("count"), "confidence": round(conf, 2),
               "freshness": _visual_flag(it.get("freshness")), "freshness_raw": it.get("freshness", "fresh"),
               "category": ing.section if ing else ""}
        if it.get("weight_g"):
            row.update(weight_g=float(it["weight_g"]), is_estimated=False, weight_text=f"{float(it['weight_g']):.0f} g")
        else:
            est = estimate_weight({"name": row["name"], "count": it.get("count") or 1, "size_px": it.get("size_px"),
                                   "confidence": conf}, wiki, ref, twin_data)
            row.update(weight_g=est["weight_g"], is_estimated=True, weight_text=est["text"], estimate=est)
        row["needs_weight"] = row["weight_g"] is None
        row["status"] = "confirm" if conf < LOW_CONFIDENCE or ing is None else "ok"
        items.append(row)
    return {"kind": "ingredients", "items": items, "reference": ref,
            "message": "" if items else "未识别到食材，可通过对话或手动添加"}


def receipt_card(raw: dict, wiki: Wiki, history: dict[str, float]) -> dict:
    items = []
    for idx, it in enumerate(raw.get("items") or []):
        base = {k: (float(it[k]) if isinstance(it.get(k), (int, float)) else None)
                for k in ("quantity", "weight_g", "unit_price", "amount")}
        done = complete_item({"name": str(it.get("name", "")), **base}, wiki, history)
        ing = wiki.ingredient(done["name"])
        done.update(id=idx, recognized_as=it.get("name", ""), name=ing.name if ing else done["name"],
                    status="ok" if ing else "confirm", is_estimated=done["estimated"],
                    weight_text=(f"{done['weight_g']:.0f} g" + ("（估算）" if done["estimated"] else "")) if done.get("weight_g") else "")
        items.append(done)
    total = raw.get("total")
    if not isinstance(total, (int, float)):
        total = round(sum(i.get("amount") or 0 for i in items), 2) or None
    return {"kind": "receipt", "label_kind": raw.get("kind", "receipt"), "merchant": raw.get("merchant") or "",
            "date": raw.get("date"), "total": total, "items": items,
            "message": "" if items else ("仅识别到总金额：记账只记总额，成本测算使用参考价（估算）" if total else "未识别到内容")}


def meal_card(raw: dict, wiki: Wiki) -> dict:
    dishes = []
    for idx, d in enumerate(raw.get("dishes") or []):
        ings = []
        for i in d.get("ingredients") or []:
            canon = wiki.resolve(str(i.get("name", "")))
            ings.append({"name": canon or i.get("name", ""), "grams": float(i.get("grams") or 0), "known": canon is not None})
        n = nutrition_of(((i["name"], i["grams"]) for i in ings), wiki)
        dishes.append({"id": idx, "name": d.get("name", f"菜{idx + 1}"), "portion": float(d.get("portion") or 1),
                       "ingredients": ings, "nutrition_total": n, "is_estimated": True})
    return {"kind": "meal", "context": raw.get("context") if raw.get("context") in ("home", "out") else "home",
            "confidence": raw.get("confidence"), "items": dishes,
            "message": "" if dishes else "未识别到菜品，可手动补充"}


async def recognize(kind: str, image: bytes, mime: str, wiki: Wiki, llm: LLMClient,
                    twin_data: dict | None = None, history: dict[str, float] | None = None,
                    hint: str = "") -> tuple[dict, dict]:
    """Returns (card, raw). Offline or on failure: an empty card that the user fills in manually."""
    prompt = {"ingredients": INGREDIENT_PROMPT, "receipt": RECEIPT_PROMPT, "meal": MEAL_PROMPT}[kind]
    try:
        raw = await llm.chat_json(prompt, f"请识别这张图片。{hint}".strip(), agent=f"vision:{kind}",
                                  images=[image_data_url(image, mime)])
    except LLMUnavailable:
        empty = {"kind": kind, "items": [], "message": "未配置 DeepSeek 多模态模型：请通过对话或手动方式补充（识别仅为辅助）"}
        if kind == "meal":
            empty["context"] = "home"
        return empty, {}
    except LLMError as exc:
        empty = {"kind": kind, "items": [], "message": f"识别失败，请手动补充（{str(exc)[:80]}）"}
        if kind == "meal":
            empty["context"] = "home"
        return empty, {"error": str(exc)[:300]}
    if not isinstance(raw, dict):
        raw = {}
    if kind == "ingredients":
        return ingredient_card(raw, wiki, twin_data), raw
    if kind == "receipt":
        return receipt_card(raw, wiki, history or {}), raw
    return meal_card(raw, wiki), raw


def apply_card_ops(card: dict, ops: list[dict], wiki: Wiki) -> tuple[dict, list[str], list[dict]]:
    """Apply edits (from tap-to-edit or chat) to a card. Returns (card, descriptions, corrections)."""
    card = copy.deepcopy(card)
    items = card.setdefault("items", [])
    done, corrections = [], []

    def find(name: str) -> dict | None:
        canon = wiki.resolve(name) or name
        return next((i for i in items if i.get("name") == canon or i.get("recognized_as") == name or i.get("name") == name), None)

    for op in ops:
        kind = op.get("op")
        if kind == "rename":
            it = find(op.get("from", ""))
            if it:
                new = wiki.resolve(op["to"]) or op["to"]
                corrections.append({"from_name": it["name"], "to_name": new})
                it.update(name=new, canonical=new if wiki.ingredient(new) else None, status="ok")
                done.append(f"{op['from']} 已改为 {new}")
        elif kind == "set":
            it = find(op.get("name", ""))
            if it:
                if op.get("weight_g") is not None:
                    if it.get("is_estimated") and it.get("weight_g"):
                        corrections.append({"name": it["name"], "estimated_g": it["weight_g"], "actual_g": op["weight_g"]})
                    it.update(weight_g=float(op["weight_g"]), is_estimated=False, needs_weight=False,
                              weight_text=f"{float(op['weight_g']):.0f} g")
                if op.get("quantity") is not None:
                    it["quantity"] = op["quantity"]
                for k in ("unit_price", "amount", "shelf_life_days", "purchase_date"):
                    if op.get(k) is not None:
                        it[k] = op[k]
                it["status"] = "ok"
                done.append(f"{it['name']} 已更新")
        elif kind == "remove":
            it = find(op.get("name", ""))
            if it:
                items.remove(it)
                done.append(f"已删除 {it['name']}")
        elif kind == "add":
            canon = wiki.resolve(op.get("name", "")) or op.get("name", "")
            ing = wiki.ingredient(canon)
            row = {"id": max([i.get("id", 0) for i in items] or [-1]) + 1, "name": canon, "canonical": ing.name if ing else None,
                   "quantity": op.get("quantity"), "weight_g": op.get("weight_g"), "is_estimated": False,
                   "status": "ok", "freshness": "fresh", "category": ing.section if ing else "",
                   "weight_text": f"{op['weight_g']:.0f} g" if op.get("weight_g") else ""}
            if row["weight_g"] is None and ing and ing.piece_g and op.get("quantity"):
                row.update(weight_g=round(op["quantity"] * ing.piece_g), is_estimated=True,
                           weight_text=f"约 {op['quantity'] * ing.piece_g:.0f} g（估算）")
            row["needs_weight"] = row["weight_g"] is None
            if card.get("kind") == "receipt":
                row = complete_item({k: row.get(k) for k in ("name", "quantity", "weight_g")} | {
                    "unit_price": op.get("unit_price"), "amount": op.get("amount")}, wiki) | {"id": row["id"], "status": "ok"}
            if card.get("kind") == "meal":
                row = {"id": row["id"], "name": op.get("dish") or canon, "portion": 1,
                       "ingredients": [{"name": canon, "grams": float(op.get("weight_g") or 100), "known": ing is not None}],
                       "is_estimated": True}
                row["nutrition_total"] = nutrition_of(((i["name"], i["grams"]) for i in row["ingredients"]), wiki)
            items.append(row)
            done.append(f"已添加 {canon}")
    return card, done, corrections
