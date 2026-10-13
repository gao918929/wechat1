import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import recognition as recognition_router

from .test_wiki_and_parsers import DEMO_ZH


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, dev_id, nickname):
    r = client.post("/api/auth/login", json={"dev_id": dev_id, "nickname": nickname})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def wait_plan(client, h, pid, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = client.get(f"/api/plans/{pid}", headers=h).json()
        if p["status"] in ("done", "failed"):
            return p
        time.sleep(0.05)
    raise AssertionError("plan did not finish")


def test_health_and_auth(client):
    assert client.get("/api/health").json()["llm_online"] is False
    assert client.get("/api/me").status_code == 401
    h, data = login(client, "alice-device", "小A")
    assert data["groups"][0]["name"] == "我的厨房" and data["groups"][0]["role"] == "admin"
    h2, data2 = login(client, "alice-device", "")
    assert data2["user"]["id"] == data["user"]["id"]  # stable dev identity


def test_full_dorm_flow(client):
    ha, a = login(client, "dorm-a", "小A")
    hb, b = login(client, "dorm-b", "小B")
    r = client.put("/api/me", headers=ha, json={"sex": "male", "age": 21, "height_cm": 175, "weight_kg": 72,
                                                 "goal": "fat_loss", "avoidances": ["spicy"]})
    assert r.status_code == 200 and r.json()["user"]["goal"] == "fat_loss"
    targets = client.get("/api/me/targets", headers=ha).json()
    assert 1850 <= targets["daily"]["kcal"] <= 1920

    g = client.post("/api/groups", headers=ha, json={"name": "302宿舍", "kind": "dorm"}).json()
    gid = g["id"]
    joined = client.post("/api/groups/join", headers=hb, json={"invite_code": g["invite_code"]}).json()
    assert len(joined["member_list"]) == 2
    client.put(f"/api/groups/{gid}", headers=ha, json={"budget_mode": "per_person", "budget_amount": 80})

    # members can't edit inventory; admins can (tiered permissions)
    assert client.post(f"/api/groups/{gid}/inventory", headers=hb, json={"items": [{"name": "鸡蛋", "quantity": 6}]}).status_code == 403
    r = client.post(f"/api/groups/{gid}/inventory/chat", headers=ha, json={"text": "冰箱里还有六个鸡蛋和两个番茄"})
    assert r.json()["ok"] and r.json()["parsed"]["intent"] == "set"
    client.post(f"/api/groups/{gid}/inventory", headers=ha, json={"items": [
        {"name": "鸡胸肉", "weight_g": 500, "purchase_date": time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))}]})
    inv = client.get(f"/api/groups/{gid}/inventory", headers=hb).json()
    names = {i["name"] for i in inv["items"]}
    assert {"鸡蛋", "番茄", "鸡胸肉"} <= names
    assert any(a["name"] == "鸡胸肉" and a["level"] == "near_expiry" for a in inv["alerts"])
    # members may mark consumption
    r = client.post(f"/api/groups/{gid}/inventory/chat", headers=hb, json={"text": "今天用了两个鸡蛋"})
    assert r.json()["ok"] and "消耗 鸡蛋" in r.json()["applied"][0]
    eggs = [i for i in client.get(f"/api/groups/{gid}/inventory", headers=ha).json()["items"] if i["name"] == "鸡蛋"]
    assert sum(i["quantity"] for i in eggs) == 4

    # plan: background job + SSE stream replay
    r = client.post(f"/api/groups/{gid}/plans", headers=ha, json={"instruction": DEMO_ZH, "alternatives": "always"})
    pid = r.json()["id"]
    plan = wait_plan(client, ha, pid)
    assert plan["status"] == "done", plan["error"]
    res = plan["result"]
    assert len(res["diners"]) == 4 and res["budget"]["total"] == 320
    assert {v["key"] for v in res["variants"]} == {"balanced", "health", "budget"}
    with client.stream("GET", f"/api/plans/{pid}/stream", headers=ha) as s:
        body = "".join(chunk for chunk in s.iter_text())
    types = [json.loads(line[6:])["type"] for line in body.splitlines() if line.startswith("data: ")]
    assert types[0] == "intent" and types[-1] == "done" and "framework" in types and "shopping" in types
    polled = client.get(f"/api/plans/{pid}?since=3", headers=ha).json()
    assert polled["events"][0]["seq"] == 3

    # notification after background completion
    notes = client.get("/api/notifications", headers=ha).json()
    assert notes["unread"] >= 1 and notes["items"][0]["title"] == "膳食计划已完成"

    # choose / feedback / edit
    assert client.post(f"/api/plans/{pid}/choose", headers=ha, json={"variant": "budget"}).json()["chosen_variant"] == "budget"
    v = next(x for x in res["variants"] if x["key"] == "budget")
    first = v["days"][0]["meals"][0]["dishes"][0]["name"]
    assert client.post(f"/api/plans/{pid}/feedback", headers=ha, json={"kind": "favorite", "dish": first}).json()["ok"]
    r = client.post(f"/api/plans/{pid}/feedback", headers=ha, json={
        "kind": "replace_dish", "variant": "budget", "day": 1, "meal": "dinner", "dish": first, "with_dish": "番茄炒蛋"})
    assert r.status_code == 200, r.text
    assert r.json()["variant"]["days"][0]["meals"][0]["dishes"][0]["name"] == "番茄炒蛋"
    assert client.post(f"/api/plans/{pid}/feedback", headers=ha, json={"kind": "rate", "score": 5}).json()["ok"]

    # shopping list + shared check-off + text export
    shop = client.get(f"/api/plans/{pid}/shopping", headers=hb).json()
    item = shop["shopping"]["sections"][0]["items"][0]["name"]
    client.post(f"/api/plans/{pid}/shopping/check", headers=hb, json={"name": item, "checked": True})
    text = client.get(f"/api/plans/{pid}/shopping/text", headers=ha).text
    assert text.startswith("【MealAgent 购物清单】") and f"☑ {item}" in text

    # mark a planned meal eaten → deduct inventory once, intake for each member
    r1 = client.post(f"/api/plans/{pid}/eat", headers=ha, json={"day": 1, "meal": "dinner"}).json()
    r2 = client.post(f"/api/plans/{pid}/eat", headers=hb, json={"day": 1, "meal": "dinner"}).json()
    assert r1["ok"] and r1["inventory_changes"] and r2["inventory_changes"] == []
    nut = client.get("/api/me/nutrition?days=7", headers=ha).json()
    assert nut["logged_days"] == 1 and nut["series"][-1]["kcal"] > 0

    # digital twin learns from feedback; group twin respects visibility
    twin = client.post("/api/me/twin/refresh", headers=ha).json()
    assert twin["data"]["variant_choices"] == {"budget": 1}
    assert twin["data"]["dish_scores"].get("番茄炒蛋", 0) > 0
    assert client.get(f"/api/groups/{gid}/twin", headers=hb).status_code == 200
    client.put(f"/api/groups/{gid}", headers=ha, json={"twin_visibility": "owner"})
    assert client.get(f"/api/groups/{gid}/twin", headers=hb).status_code == 403
    assert client.get(f"/api/groups/{gid}/twin", headers=ha).status_code == 200

    # second identical request is served from the cache? (inventory changed → new key, so it re-plans)
    r = client.post(f"/api/groups/{gid}/plans", headers=ha, json={"instruction": "下周三天午餐", "days": 3, "meals": ["lunch"]})
    p2 = wait_plan(client, ha, r.json()["id"])
    assert p2["status"] == "done" and p2["result"]["days"] == 3
    assert client.get(f"/api/groups/{gid}/plans", headers=hb).json()[0]["id"] == p2["id"]


def test_manual_card_and_receipt_flow(client):
    h, data = login(client, "receipt-user", "小C")
    gid = data["groups"][0]["id"]
    rec = client.post("/api/recognitions/manual", headers=h, data={"kind": "receipt", "group_id": gid}).json()
    r = client.post(f"/api/recognitions/{rec['id']}/chat", headers=h, json={"text": "加上一斤猪里脊"}).json()
    assert r["card"]["items"][0]["name"] == "猪里脊" and r["card"]["items"][0]["weight_g"] == 500
    r = client.patch(f"/api/recognitions/{rec['id']}", headers=h, json={
        "ops": [{"op": "set", "name": "猪里脊", "amount": 17.0}], "total": 17.0, "merchant": "物美"}).json()
    done = client.post(f"/api/recognitions/{rec['id']}/confirm", headers=h, json={}).json()
    assert done["total"] == 17.0 and done["added_to_inventory"] == ["猪里脊"]
    report = client.get(f"/api/groups/{gid}/expenses/report?period=week", headers=h).json()
    assert report["total"] == 17.0 and report["by_category"][0]["label"] == "肉蛋"


def test_photo_recognition_with_vision_model(client, fake_llm_cls, monkeypatch):
    h, data = login(client, "photo-user", "小D")
    gid = data["groups"][0]["id"]
    fake = fake_llm_cls({"vision:ingredients": {
        "items": [{"name": "白菜", "count": 1, "size_px": 400, "confidence": 0.92, "freshness": "fresh"},
                  {"name": "鸡蛋", "count": 2, "size_px": 100, "confidence": 0.95, "freshness": "fresh"},
                  {"name": "不明物体", "count": 1, "confidence": 0.3}],
        "reference": {"key": "egg", "size_px": 100}}})
    monkeypatch.setattr(recognition_router, "new_client", lambda: fake)
    img = io.BytesIO(b"\xff\xd8\xff\xe0fakejpeg")
    rec = client.post("/api/recognitions", headers=h, data={"kind": "ingredients", "group_id": gid},
                      files={"file": ("fridge.jpg", img, "image/jpeg")}).json()
    assert fake.log[0]["images"] is True
    items = {i["name"]: i for i in rec["card"]["items"]}
    assert "估算" in items["大白菜"]["weight_text"] and 1400 <= items["大白菜"]["weight_g"] <= 1500
    assert items["不明物体"]["status"] == "confirm"  # low confidence → awaiting confirmation
    r = client.post(f"/api/recognitions/{rec['id']}/chat", headers=h, json={"text": "把白菜改成1800克"}).json()
    assert {i["name"]: i for i in r["card"]["items"]}["大白菜"]["weight_g"] == 1800
    done = client.post(f"/api/recognitions/{rec['id']}/confirm", headers=h, json={}).json()
    assert set(done["added"]) == {"大白菜", "鸡蛋"} and done["skipped"] == ["不明物体"]
    twin = client.post("/api/me/twin/refresh", headers=h).json()["data"]
    assert twin["calibration"]["大白菜"]["factor"] > 1.1  # correction remembered for future estimates


def test_meal_review_out_vs_home(client):
    h, data = login(client, "meal-user", "小E")
    gid = data["groups"][0]["id"]
    client.post(f"/api/groups/{gid}/inventory", headers=h, json={"items": [{"name": "鸡蛋", "weight_g": 300}]})
    for context, expect_deduct in (("out", False), ("home", True)):
        rec = client.post("/api/recognitions/manual", headers=h, data={"kind": "meal", "group_id": gid}).json()
        client.patch(f"/api/recognitions/{rec['id']}", headers=h, json={
            "context": context, "ops": [{"op": "add", "name": "鸡蛋", "weight_g": 100, "dish": "蒸蛋羹"}]})
        done = client.post(f"/api/recognitions/{rec['id']}/confirm", headers=h, json={"meal": "lunch"}).json()
        assert done["context"] == context and done["nutrition"]["kcal"] == pytest.approx(139, abs=1)
        assert bool(done["inventory_changes"]) is expect_deduct
    eggs = client.get(f"/api/groups/{gid}/inventory", headers=h).json()["items"][0]
    assert eggs["weight_g"] == 200


def test_websocket_sync(client):
    ha, a = login(client, "ws-a", "甲")
    gid = a["groups"][0]["id"]
    token = ha["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/groups/{gid}?token={token}") as ws:
        client.post(f"/api/groups/{gid}/inventory", headers=ha, json={"items": [{"name": "土豆", "quantity": 3}]})
        msg = ws.receive_json()
        assert msg["type"] == "inventory.updated" and msg["names"] == ["土豆"]
