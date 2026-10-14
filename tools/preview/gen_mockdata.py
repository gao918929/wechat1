"""Generate realistic preview data by driving the real backend (offline rule engine).

    cd backend && python ../tools/preview/gen_mockdata.py

Writes tools/preview/mockdata.json: API responses for every mini-program page.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent / "backend"
tmp = tempfile.mkdtemp(prefix="mealagent-preview-")
os.environ.update(MEALAGENT_DATABASE_URL=f"sqlite:///{tmp}/preview.db", MEALAGENT_UPLOAD_DIR=f"{tmp}/uploads",
                  MEALAGENT_OFFLINE="1", DEEPSEEK_API_KEY="", WECHAT_APPID="")
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.recognition import ingredient_card  # noqa: E402
from app.wiki import get_wiki  # noqa: E402

DEMO = ("我在减脂，身高175cm体重72kg，宿舍4个人，这周伙食预算每人80元，我不吃辣不吃海鲜，"
        "冰箱里有番茄、鸡蛋和快过期的鸡胸肉，帮我们规划一周减脂晚餐")


def main() -> None:
    out: dict = {}
    with TestClient(app) as c:
        def login(dev: str, nick: str) -> dict:
            r = c.post("/api/auth/login", json={"dev_id": dev, "nickname": nick}).json()
            return {"Authorization": "Bearer " + r["token"]}

        h = login("preview-me", "小明")
        c.put("/api/me", headers=h, json={"sex": "male", "age": 21, "height_cm": 175, "weight_kg": 72, "goal": "fat_loss",
                                          "avoidances": ["辣", "海鲜"], "allergens": ["花生"], "likes": ["牛肉", "西兰花"]})
        g = c.post("/api/groups", headers=h, json={"name": "302 宿舍", "kind": "dorm"}).json()
        gid = g["id"]
        for nick in ("小红", "小刚", "小李"):
            c.post("/api/groups/join", headers=login(f"preview-{nick}", nick), json={"invite_code": g["invite_code"]})
        c.put(f"/api/groups/{gid}", headers=h, json={"budget_mode": "per_person", "budget_amount": 80})
        c.post(f"/api/groups/{gid}/inventory/chat", headers=h, json={"text": "冰箱里还有六个鸡蛋和三个番茄"})
        old = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        older = time.strftime("%Y-%m-%d", time.localtime(time.time() - 2 * 86400))
        c.post(f"/api/groups/{gid}/inventory", headers=h, json={"items": [
            {"name": "鸡胸肉", "weight_g": 500, "purchase_date": old},
            {"name": "菠菜", "weight_g": 300, "is_estimated": True, "freshness": "not_fresh"},
            {"name": "豆腐", "quantity": 1, "purchase_date": older},
            {"name": "大白菜"}, {"name": "大米", "weight_g": 5000}, {"name": "牛奶", "quantity": 2}]})
        for amt, m, items in ((86.5, "物美超市", [{"name": "鸡胸肉", "amount": 28.5, "weight_g": 1200},
                                                 {"name": "西兰花", "amount": 12, "weight_g": 900},
                                                 {"name": "鸡蛋", "amount": 18, "quantity": 30}]),
                              (23.8, "菜市场", [{"name": "番茄", "amount": 9.6, "weight_g": 1200},
                                               {"name": "小白菜", "amount": 6, "weight_g": 1000}]),
                              (15, "", [])):
            c.post(f"/api/groups/{gid}/expenses", headers=h, json={"total_amount": amt, "merchant": m, "items": items})

        pid = c.post(f"/api/groups/{gid}/plans", headers=h, json={"instruction": DEMO, "alternatives": "always"}).json()["id"]
        while True:
            plan = c.get(f"/api/plans/{pid}?since=0", headers=h).json()
            if plan["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        c.post(f"/api/plans/{pid}/feedback", headers=h, json={"kind": "favorite", "dish": "番茄炒蛋"})
        c.post(f"/api/plans/{pid}/feedback", headers=h, json={"kind": "rate", "score": 5})
        c.post(f"/api/plans/{pid}/choose", headers=h, json={"variant": "balanced"})
        c.post(f"/api/plans/{pid}/shopping/check", headers=h, json={"name": "西兰花", "checked": True})

        nutrition = c.get("/api/me/nutrition?days=7", headers=h).json()
        kc = [1650, 1920, 1780, 2210, 1840, 1700, 1268]  # a believable week for the chart
        for i, d in enumerate(nutrition["series"]):
            d.update(kcal=kc[i], protein=95 + i * 3, fat=52, carb=190, vc=80, ca=600, fe=14, salt_g=6.1, vegetable_g=320,
                     score=[86, 78, 90, 62, 84, 88, 74][i], reasons=["能量偏离目标 17%"] if i == 3 else [])
        nutrition.update(logged_days=7, score=80, average={"kcal": 1766, "protein": 104, "fat": 52, "carb": 190})

        twin = c.post("/api/me/twin/refresh", headers=h).json()
        twin.update(visibility="仅本人可见、可编辑", updated_at="2026-10-14T08:00:00")
        wiki = get_wiki()
        card = ingredient_card({"items": [
            {"name": "白菜", "count": 1, "size_px": 400, "confidence": 0.92, "freshness": "fresh"},
            {"name": "鸡蛋", "count": 6, "size_px": 100, "confidence": 0.95, "freshness": "fresh"},
            {"name": "菠菜", "count": 1, "confidence": 0.81, "freshness": "wilted"},
            {"name": "不明蔬菜", "count": 1, "confidence": 0.35}], "reference": {"key": "egg", "size_px": 100}}, wiki, None)
        out.update(
            meta=c.get("/api/meta").json(), me=c.get("/api/me", headers=h).json(),
            targets=c.get("/api/me/targets", headers=h).json(), group=c.get(f"/api/groups/{gid}", headers=h).json(),
            inventory=c.get(f"/api/groups/{gid}/inventory", headers=h).json(),
            plans=c.get(f"/api/groups/{gid}/plans", headers=h).json(),
            plan=c.get(f"/api/plans/{pid}?since=0", headers=h).json(),
            shopping=c.get(f"/api/plans/{pid}/shopping", headers=h).json(),
            report=c.get(f"/api/groups/{gid}/expenses/report?period=week", headers=h).json(),
            expenses=c.get(f"/api/groups/{gid}/expenses", headers=h).json(),
            nutrition=nutrition, nutrition_today={**nutrition, "series": nutrition["series"][-1:]},
            group_nutrition=c.get(f"/api/groups/{gid}/nutrition", headers=h).json(),
            twin=twin, notifications=c.get("/api/notifications", headers=h).json(),
            dishes=c.get("/api/wiki/dishes", headers=h).json(),
            recognition={"id": 9, "kind": "ingredients", "status": "pending", "group_id": gid, "upload_id": 1,
                         "card": card, "message": "", "created_at": "2026-10-14T08:00:00"},
            group_id=gid, plan_id=pid,
        )
    (HERE / "mockdata.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("wrote", HERE / "mockdata.json")


if __name__ == "__main__":
    main()
