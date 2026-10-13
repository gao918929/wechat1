"""Conversational edits: LLM first (when configured), rule parser as fallback."""
from __future__ import annotations

from ..llm import LLMClient, LLMError
from ..wiki import Wiki
from .nl import parse_card_command, parse_inventory_command

INVENTORY_PROMPT = """你是 MealAgent 的库存对话助手。把用户的话转换为库存操作。
intent："set"（说明现有数量，如“还有两个鸡蛋”）、"add"（买了/新增）、"consume"（用了/吃了）、"remove"（扔了/坏了）。
食材名用中文标准名；数量用 quantity（个数）或 weight_g（克，1斤=500g）。
输出 JSON：{"intent":"set|add|consume|remove","items":[{"name":"","quantity":null,"weight_g":null}]}"""

CARD_PROMPT = """你是 MealAgent 识别结果清单卡片的编辑助手。根据用户的话输出对卡片的修改操作：
{"op":"rename","from":"原名","to":"新名"} / {"op":"set","name":"","weight_g":克,"quantity":个数} /
{"op":"remove","name":""} / {"op":"add","name":"","weight_g":null,"quantity":null}
输出 JSON：{"ops":[...]}"""


async def inventory_ops(text: str, wiki: Wiki, llm: LLMClient) -> dict:
    if llm.online:
        try:
            resp = await llm.chat_json(INVENTORY_PROMPT, text, agent="chat")
            items = []
            for it in resp.get("items") or []:
                canon = wiki.resolve(str(it.get("name", "")))
                if canon:
                    items.append({"name": canon, **{k: float(it[k]) for k in ("quantity", "weight_g")
                                                    if isinstance(it.get(k), (int, float))}})
            if items and resp.get("intent") in ("set", "add", "consume", "remove"):
                return {"intent": resp["intent"], "items": items, "parser": "llm"}
        except LLMError:
            pass
    return {**parse_inventory_command(text, wiki), "parser": "rules"}


async def card_ops(text: str, card: dict, wiki: Wiki, llm: LLMClient) -> tuple[list[dict], str]:
    if llm.online:
        try:
            resp = await llm.chat_json(CARD_PROMPT, {"text": text, "card": [
                {"name": i.get("name"), "weight_g": i.get("weight_g"), "quantity": i.get("quantity")}
                for i in card.get("items", [])]}, agent="chat")
            ops = [o for o in resp.get("ops") or [] if isinstance(o, dict) and o.get("op")]
            if ops:
                return ops, "llm"
        except LLMError:
            pass
    return parse_card_command(text, wiki), "rules"
