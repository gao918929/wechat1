"""End-to-end demo against a running backend (the design document's Section 7 script).

    uvicorn app.main:app --port 8000      # in another terminal
    python scripts/demo.py --base http://127.0.0.1:8000

Creates a 4-person dorm, records fridge inventory (near-expiry chicken breast), sends the
natural-language instruction, prints the streamed agent progress and the resulting plans.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid

import httpx

INSTRUCTION = ("我在减脂，身高175cm体重72kg，宿舍4个人，这周伙食预算每人80元，我不吃辣不吃海鲜，"
               "冰箱里有番茄、鸡蛋和快过期的鸡胸肉，帮我们规划一周减脂晚餐")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=300)
    run = uuid.uuid4().hex[:6]

    def login(name: str) -> dict:
        r = c.post("/api/auth/login", json={"dev_id": f"demo-{run}-{name}", "nickname": name}).json()
        return {"Authorization": f"Bearer {r['token']}"}

    me = login("小明")
    c.put("/api/me", headers=me, json={"sex": "male", "age": 21, "height_cm": 175, "weight_kg": 72, "goal": "fat_loss",
                                        "avoidances": ["辣", "海鲜"]})
    group = c.post("/api/groups", headers=me, json={"name": "302宿舍", "kind": "dorm"}).json()
    for name in ("小红", "小刚", "小李"):
        c.post("/api/groups/join", headers=login(name), json={"invite_code": group["invite_code"]})
    gid = group["id"]
    print(f"宿舍 {group['name']}（邀请码 {group['invite_code']}）已创建，4 名成员")

    c.post(f"/api/groups/{gid}/inventory/chat", headers=me, json={"text": "冰箱里还有六个鸡蛋和三个番茄"})
    three_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
    c.post(f"/api/groups/{gid}/inventory", headers=me,
           json={"items": [{"name": "鸡胸肉", "weight_g": 500, "purchase_date": three_days_ago}]})
    alerts = c.get(f"/api/groups/{gid}/inventory", headers=me).json()["alerts"]
    print("临期提醒：", "、".join(f"{a['name']}（{a['label']}）" for a in alerts) or "无")

    plan = c.post(f"/api/groups/{gid}/plans", headers=me, json={"instruction": INSTRUCTION, "alternatives": "always"}).json()
    print(f"\n指令：{INSTRUCTION}\n")
    with c.stream("GET", f"/api/plans/{plan['id']}/stream", headers=me) as s:
        for line in s.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            t, d = ev["type"], ev["data"]
            if t == "intent":
                print(f"[调度器] {len(d['diners'])} 人 · {d['days']} 天 · 预算 {d['budget']['total']} · 模式 {d['mode']}")
            elif t == "agent":
                print(f"[{d['title']}] ({d['mode']}, {d['seconds']}s) {d['summary']}")
            elif t == "validation":
                print(f"[校验:{d['variant']}] 第{d['attempt'] + 1}轮 {'通过' if d['passed'] else '未通过：' + '；'.join(d['issues'][:2])}")
            elif t == "revision":
                for r in d["rounds"]:
                    print(f"[回退→{r['title']}] {'；'.join(r['applied'][:3]) or '无修改'}")
            elif t == "variant":
                s_ = d["summary"]
                print(f"[方案] {d['title']}：¥{s_['total_cost']}（人均 ¥{s_['per_person_cost']}）")
            elif t == "day":
                day = d["day"]
                print(f"  第{day['day']}天 " + " / ".join("、".join(x["name"] for x in m["dishes"]) for m in day["meals"]))
            elif t == "shopping":
                print(f"[购物清单] {sum(len(sec['items']) for sec in d['shopping']['sections'])} 项，¥{d['shopping']['total_cost']}")
            elif t in ("done", "error"):
                print(f"[{t}] {d}")
    print("\n" + c.get(f"/api/plans/{plan['id']}/shopping/text", headers=me).text)


if __name__ == "__main__":
    main()
