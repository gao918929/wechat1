# MealAgent · AI 膳食统筹微信小程序

English | [中文](README.zh-CN.md) · 📋 [Project status & to-do (Chinese)](docs/PROJECT_STATUS.md)

An AI meal-coordination WeChat mini program built from
[`MealAgent_Project_Design_Document_Final_EN.md`](MealAgent_Project_Design_Document_Final_EN.md) (V3.1).
It connects six stages: **inventory → budget → health → multi-agent weekly planning → shopping → post-meal review**.
**Dietary digital twins** learn from every edit, rating and correction.

![Mini program screens in the "Pixel Kitchen" pixel-art style (browser approximation)](docs/preview.png)

The UI is an 8-bit cooking game: hand-drawn pixel icons and animated sprites (Tomato Chef and the four agent buddies), notched pixel windows, hard shadows and stepped animations. Fonts (Fusion Pixel / Press Start 2P, OFL) load at runtime from the backend. Design spec, art prompts and animation catalogue: [`docs/PIXEL_STYLE.md`](docs/PIXEL_STYLE.md); art sources in `art/pixel/` are built with `tools/pixelart.py`; page screenshots come from `tools/preview/`.

```
miniprogram/   WeChat mini program (12 pages, native WXML/WXSS/JS)
backend/       FastAPI backend: business services, DeepSeek client, multi-agent orchestrator
llm_wiki/      Structured-Markdown knowledge base shared by all agents (ingredients, diet models, rules, dishes)
```

## Feature map (design document → code)

| Doc section | What it does | Where |
|---|---|---|
| 4.1 Inventory: photo / receipt / chat entry | Photos go to DeepSeek multimodal and come back as an editable **item-list card**. Users can tap to edit an item or say “把白菜改成400克” | `routers/recognition.py`, `services/recognition.py`, `services/chat.py`, `pages/recognize` |
| 4.1.2 Reference-object estimation | Estimates weight from the size ratio to a reference object (egg by default) in the photo. Results carry a ±15%/25% range and the label “估算”. User corrections calibrate later estimates through the twin | `services/estimation.py`, `llm_wiki/03_rules/portions.md` |
| 4.1.3 Freshness alerts | Shelf-life thresholds per food category. The date comes from the receipt or, failing that, the day the item was added. A visual “not fresh” flag overrides the date | `services/inventory.py`, `03_rules/shelf_life.md` |
| 4.1.4 Deduction | Automatic: meal-photo review deducts what was cooked at home (eating out does not touch inventory). Manual: “今天用了两个鸡蛋”, or “吃了 ✓” on a planned meal | `routers/recognition.py`, `routers/plans.py` |
| 4.2 Budget & expense tracking | The ledger stores the **actual amount paid**. Cost estimates use **historical prices first**, then reference prices labelled “估算”. Missing unit prices are filled in tiers. Budgets are per person by default, with a switch to a total budget. Weekly and monthly reports | `services/pricing.py`, `routers/expenses.py`, `pages/budget` |
| 4.3 Diet-group models, hard/soft constraints | 10 diet models. Allergens are a hard veto, and that includes seasonings (oyster sauce counts as seafood). Taste dislikes are soft and the user can override them. Separate dishes per diner are switched on only when needed, with “适合谁” labels | `agents/context.py`, `llm_wiki/02_dietary_group_models/` |
| 4.4 Health metrics | Mifflin-St Jeor energy and macro targets per diet model, following the Chinese DRIs (2023). Every output carries the medical disclaimer | `services/nutrition.py` |
| 4.6 Multi-person collaboration | Households and dorms with invite codes, admin/member roles and a shared budget. WebSocket keeps inventory, shopping check-offs and plans in sync | `routers/groups.py`, `realtime.py`, `app.js` |
| 4.7 Nutrition analytics | Daily and weekly calories, macros, micronutrient estimates and a health score, for one person or the whole group. Data sources are cited | `routers/users.py`, `pages/nutrition` |
| 4.8 Shopping list | Plan needs minus inventory, sorted by supermarket section, with total and per-person cost and budget overruns highlighted. Export by copying text or saving an image | `services/shopping.py`, `pages/shopping` |
| 4.9 Post-meal review | Tells home cooking from eating out. Records the deviation from the plan and feeds it to the twin | `services/recognition.py` |
| 4.10 Digital twins | Personal twin (visible to and editable by the owner only) and group twin (visibility: owner / selected members / all). Built from feedback events, refreshed weekly or on demand | `services/twin.py`, `pages/twin` |
| 5 Multi-agent orchestration | Central orchestrator plus **four agents, each making its own LLM call**. Three-layer validator that sends failures back to the responsible agent (≤3 retries). Plans A/B/C ranked by twin data. Streaming over SSE; generation continues in the background and notifies when done; result cache | `agents/`, `jobs.py` |

## How a plan is generated

```
instruction ──► Orchestrator: parse intent (LLM, rule parser as fallback) + build context from DB
                 │  diners & targets · hard/soft constraints · inventory (+ items mentioned in the text)
                 │  price memory · merged personal+group twin · candidate dishes (hard veto applied)
                 ▼
     ┌───────────── parallel, independent LLM calls (own system prompt + own context) ─────────────┐
     │ Health Adaptation (P1) │ Iterative Optimization (P2) │ Inventory Priority (P3) │ Budget (P4) │
     └──────────────────────────────────────────────────────────────────────────────────────────────┘
                 ▼  stream: "framework"
       Orchestrator composes plan B (LLM call) ─► finalize: per-diner portions, nutrition, cost, labels
                 ▼
       Validator: hard veto → inventory → nutrition → budget
         └─ failure ► issues routed to the responsible agent's revise() → ops applied → re-validate (≤3)
                 ▼  conflicts? (tight budget, unused near-expiry stock, rollbacks, differing needs)
       Plans A (health-first) and C (budget-first) built in parallel ─► twin-weighted ranking
                 ▼  stream: variants → days → shopping list → done (+ notification / WeChat subscribe message)
```

The deterministic facts (energy targets, shelf life, prices, allergen matching, validation) are
computed in code from the knowledge base. The LLM agents add judgement on top: which dishes, which
schedule, which substitutions. Agents never touch the database. Every agent call is logged and
returned in `result.llm_usage`.

## Quick start

### 1. Backend (Python ≥ 3.10)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set DEEPSEEK_API_KEY (see below)
uvicorn app.main:app --host 0.0.0.0 --port 8000
# API docs: http://127.0.0.1:8000/docs
```

DeepSeek settings in `.env`:

- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`), `DEEPSEEK_MODEL` (default `deepseek-chat`):
  the orchestrator and the four agents.
- `DEEPSEEK_VISION_MODEL` (+ optional `DEEPSEEK_VISION_BASE_URL` / `DEEPSEEK_VISION_API_KEY`): photo recognition.
  Point these at a **vision-capable DeepSeek deployment** that accepts OpenAI-style `image_url` content.
  If your endpoint serves text only, photo recognition will fail gracefully and fall back to manual or chat entry.

**Offline mode.** Without an API key (or with `MEALAGENT_OFFLINE=1`) the backend still runs fully, on the
rule-based engine: every agent's deterministic analysis plus a scoring-based composer. It is meant for
development and tests. Photo recognition then returns an empty card that you fill in by chat. Use DeepSeek
for the real demo; the UI shows which mode produced each plan (“LLM” or “规则”).

Run the design document's Section 7 demo end to end against a running server:

```bash
python scripts/demo.py --base http://127.0.0.1:8000
```

### 2. Mini program

1. Open **WeChat DevTools** → Import → choose the `miniprogram/` folder.
2. Replace `appid` in `miniprogram/project.config.json` with yours, or use a test account.
3. Edit `miniprogram/config.js`. Keep `baseUrl` / `wsUrl` at `127.0.0.1:8000` for the simulator. For a real phone,
   use your computer's LAN IP and tick “不校验合法域名” in DevTools.
4. Login: when `WECHAT_APPID`/`WECHAT_SECRET` are set, the backend calls `code2session`. Otherwise it uses a stable
   per-device dev id, so local development needs no WeChat credentials.
5. Optional: set `planTemplateId` (and `WECHAT_PLAN_TEMPLATE_ID` on the backend) to get a WeChat subscription
   message when a plan finishes in the background.

Pages: 首页 · 冰箱 · 计划 · 账本 · 我的 (tab bar), plus plan detail (streaming), recognition card,
shopping list, nutrition, group management, digital twin and notifications.

Production needs HTTPS/WSS domains registered in the mini program console.

### 3. Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

The 28 tests cover: wiki parsing; the Chinese and English parsers (including the demo instruction);
nutrition targets; tiered price completion; reference-object estimation and calibration; freshness; the
shopping list; the demo script end to end (no spicy or seafood, near-expiry chicken used by day 2, within
budget, three valid plans); hard constraints including seasonings; separate dishes for a pregnant member;
budget-agent rollback; twin-weighted preferences; a **fake-LLM test showing each agent makes its own call with
its own prompt**; and the full API flow (login → group → permissions → chat inventory → plan job + SSE replay
→ choose/edit/rate → shopping check-off → mark eaten → twin learning and visibility → receipt ledger → photo
recognition with estimation and correction → home vs. eating-out review → WebSocket sync).

## Knowledge base (LLM Wiki)

Plain Markdown that people can edit and that the backend parses directly. The format rules are in
`llm_wiki/00_index.md`:

- `01_ingredients/*.md`: one table row per ingredient: nutrition per 100 g, price range (CNY/kg), shelf
  category, single-piece weight and size, allergens and tags. Add a row and the ingredient is immediately
  usable for planning, costing and estimation. More sources (such as USDA) can be added as extra columns or files.
- `02_dietary_group_models/*.md`: `## Parameters` (machine-readable) plus guidance text that is injected into agent prompts.
- `03_rules/*.md`: shelf life, reference objects, conflict priorities, budget definitions, nutrition thresholds.
- `04_dish_templates/*.md`: dish templates with ingredient amounts per serving. Agents may also propose new
  dishes made from known ingredients; the validator rejects unknown ingredients.

Nutrition values are approximate figures based on the *China Food Composition Tables* (6th ed.). Targets
follow the *Chinese DRIs (2023)* and the *Dietary Guidelines for Chinese Residents (2022)*. Check the values and
calibrate reference prices for your city before the defense.

## API overview

| Area | Endpoints |
|---|---|
| Auth / profile | `POST /api/auth/login`, `GET/PUT /api/me`, `GET /api/me/targets`, `GET /api/me/nutrition`, `GET /api/me/meals` |
| Twin | `GET/PUT /api/me/twin`, `POST /api/me/twin/refresh`, `GET /api/groups/{id}/twin` |
| Groups | `GET/POST /api/groups`, `POST /api/groups/join`, `GET/PUT /api/groups/{id}`, `PUT/DELETE /api/groups/{id}/members/{uid}`, `GET /api/groups/{id}/nutrition` |
| Inventory | `GET/POST /api/groups/{id}/inventory`, `POST /api/groups/{id}/inventory/chat`, `POST /api/groups/{id}/inventory/consume`, `PUT/DELETE /api/inventory/{id}`, `POST /api/inventory/{id}/consume` |
| Recognition | `POST /api/recognitions` (multipart photo), `POST /api/recognitions/manual`, `GET/PUT /api/recognitions/{id}`, `POST /api/recognitions/{id}/chat`, `POST /api/recognitions/{id}/confirm`, `GET /api/uploads/{id}` |
| Expenses | `GET/POST /api/groups/{id}/expenses`, `GET /api/groups/{id}/expenses/report?period=week|month`, `DELETE /api/expenses/{id}` |
| Plans | `POST /api/groups/{id}/plans`, `GET /api/groups/{id}/plans`, `GET /api/plans/{id}?since=n`, `GET /api/plans/{id}/stream` (SSE), `POST /api/plans/{id}/choose`, `POST /api/plans/{id}/feedback`, `POST /api/plans/{id}/eat` |
| Shopping | `GET /api/plans/{id}/shopping`, `POST /api/plans/{id}/shopping/check`, `GET /api/plans/{id}/shopping/text` |
| Misc | `GET /api/health`, `GET /api/meta`, `GET /api/wiki/ingredients|dishes|sources`, `GET /api/notifications`, `WS /ws/groups/{id}?token=` |

## Scope notes

- All dietary suggestions are general guidance based on the *Dietary Guidelines for Chinese Residents*, not
  medical advice. Recognition is an aid: every result can be corrected, and estimates are always labelled “估算”.
- Receipt images are treated as sensitive. Only members of the group can fetch them, and they are used only
  for the expense ledger.
- SQLite is the default store, so the local demo needs no extra setup. Set `MEALAGENT_DATABASE_URL` to any
  SQLAlchemy URL to change it.
