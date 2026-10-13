# MealAgent

**AI 膳食统筹 · 原生微信小程序 + FastAPI 后端 + LLM Wiki**

本分支将 [`MealAgent_Project_Design_Document_Final_EN.md`](MealAgent_Project_Design_Document_Final_EN.md) 落成了可运行首版，包含真实多 Agent 调用路径、服务端约束校验、库存/账单/复盘持久化以及微信小程序页面。

> **交付状态必须如实理解：不是“全部需求已验收”。** 不包含 API 密钥、微信生产账号或伪造的模型结果。自动化测试使用仅存在于测试目录的固定响应；真实 DeepSeek 调用、微信开发者工具/真机、微信订阅通知和完整演示录像尚待外部配置与实测。详细差异见 [验收矩阵](docs/ACCEPTANCE.md)。

## 1. 本地启动（Windows）

安装 Python 3.13 或 3.14，在仓库根目录运行：

```powershell
Copy-Item .env.example .env
# 编辑 .env：真实 AI 需要 DEEPSEEK_API_KEY；开发登录配置见下。
.\scripts\start.ps1
```

脚本创建独立 `.venv` 并安装依赖，只监听本机 `127.0.0.1:8000`。

- 本地验收界面：`http://127.0.0.1:8000`
- 交互式 API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

首次使用本地网页，请在 `.env` 中启用开发登录：

```dotenv
ALLOW_DEV_LOGIN=true
DEV_LOGIN_KEY=请换成至少16字符的随机字符串
```

密钥可在本地生成：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

登录时填写开发用户名与该密钥。开发用户名相同会返回同一测试账户，所以**共享开发密钥不是生产身份认证**。开发登录仅允许回环客户端，公网部署必须关闭。应用不读取 Codex 的凭据。

macOS / Linux：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
# 编辑配置后：
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

## 2. 配置真实 AI

```dotenv
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_VISION_MODEL=deepseek-flash
```

模型名与服务地址均可改；需使用支持 Chat Completions、结构化 JSON 和流式输出的接口，视觉模型还需支持图片输入。如果账号没有对应模型权限，应换成账号实际可用的模型，不能通过硬编码答案绕过。

- 四个 Agent 有各自独立 system prompt、上下文及 HTTP 调用。
- 库存、健康、迭代三个 Agent 并行，预算 Agent 汇总生成候选方案。
- 服务端重新计算原料分配、逐人营养与采购价格，不采信模型自行声称的总数。
- 失败最多交回对应 Agent 修正 3 次；仍不合格则展示错误，不发布不安全半成品。
- 图片经过尺寸检查、解码与 EXIF 清除；原始图片不持久保存。
- 可设置 `VISION_FALLBACK_*` 使用额外的兼容 OCR/视觉服务。默认不启用，也不会悄悄把图片传给其他服务。

## 3. 微信小程序

1. 微信开发者工具导入 **`miniprogram` 目录**。
2. 将 `project.config.json` 的占位 `touristappid` 改成你的实际 AppID（建议使用开发者工具私有配置，避免误提交账号设置）。
3. 后端配置同一微信应用的 `WECHAT_APP_ID` / `WECHAT_APP_SECRET`。
4. 登录页填写后端地址。开发工具本机可用 `http://127.0.0.1:8000`，并仅在本地调试时调整开发工具的合法域名校验设置。
5. 真机 / 发布环境需配置 HTTPS 请求和上传域名、WSS socket 域名及有效证书；手机的 `127.0.0.1` 不是电脑。
6. 小程序用 `wx.login → code2Session → 自有会话 token` 登录。开发登录只用于本机测试，不可作为正式登录替代品。

页面：今日、冰箱、计划、记录、个人画像、登录、识别确认、数字孪生。

SSE 使用 `wx.request(enableChunked)` 与增量 UTF-8 解码；不支持流式环境自动由轮询兜底。离开页面只断开结果订阅，不取消后台任务。共享事件使用 WebSocket，认证 token 放在首条消息中而不是 URL。

**尚未运行微信官方编译器或真机测试。** 仓库中的静态检查不能替代这一步。

## 4. 首次操作顺序

1. 登录，创建家庭/宿舍；将一次性显示的邀请码交给需要加入的成员。
2. 每位成员填写自己的画像、过敏原、禁忌与口味。特殊人群必须填写专业确认的每餐目标。
3. 普通成人可填写身高、体重、年龄与生理性别以使用明确标注的估算参考，或手动确认每餐目标。估算不自动开出减脂热量赤字，也不冒充 DRIs。
4. 添加食材（原料可食重量、实际食用期限），或拍照后逐项确认。不同批次分开保存。
5. 为需要购买的食材设置真实来源的参考价格，或录入真实收据。没有价格的采购项会触发校验，不会凭空补价。
6. 选择共餐成员、预算口径和日期，发起 1–7 天晚餐计划。已有库存优先抵扣，预算按需新购食材计算。
7. 比较多个方案的成本、取舍和营养，选用后共享给成员；采购清单可复制，小程序还可生成图片。
8. 小票确认实付金额后，一次性同步账单、库存及可核算的历史单价。
9. 餐后记录个人实际摄入；家中餐可显式确认库存扣减，外食禁止扣库存。下次规划读取实际摄入和偏好反馈。

没有 API 密钥仍可使用手动库存、预算、账单、个人画像和权限功能；AI 端点明确报未配置，不返回假结果。

## 5. 数据与约束

- 库存、账单、画像、草稿、任务和事件写入 SQLite，默认 `data/mealagent.sqlite3`；数据库不提交 Git。
- 金额以整数分保存；实际账单不可直接修改。收据重复确认及库存消耗有幂等性保护。
- 折扣按已知行金额比例分摊，整数余数守恒。估重数据不会成为“精确历史单价”。
- 过敏原 / 明确慢病禁忌始终为硬约束，包含分餐方案；不会因预算或营养目标而覆盖。
- 乐观版本号防止库存编辑覆盖别人的改动；批量扣减在同一事务内完成，失败全部回滚。
- 模型计算期间若画像、库存或价格改变，旧结果不会被静默采用；选用前也检查过期输入。
- 个人孪生只有本人可读，集体孪生按权限显示。个人未共享偏好不进入集体记忆。
- 视觉“新鲜”不能证明安全。实际储存条件/包装信息/用户确认日期是必要输入，未做食品安全保证。
- 报表只汇总已记录餐次；未记录不等于零摄入。目标匹配度不是临床健康评分。

## 6. 营养标准与知识库

初始 19 种食材来自官方 USDA FoodData Central SR Legacy，保留 FDC ID、来源 URL、提取日期与原始 JSON。**没有编造中国食物成分表或 DRIs 数值。**

获得合法来源后可导入规范化数据：

```bash
python scripts/import_reference.py nutrients your_food_data.json
python scripts/import_reference.py targets your_meal_targets.json
```

示例结构与规则见 [数据说明](docs/DATA.md)。导入文件保存在被 Git 忽略的 `data/` 中。目录代码会动态加载；库存与过敏原仍由服务端验证。

`llm_wiki/` 包括索引、食材来源、人群模型、约束规则、份量/价格规则及菜式结构模板。模板只是指导材料，不是硬编码演示食谱。

## 7. 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
node backend/tests/test_sse.cjs
node scripts/check-miniprogram.cjs
node --check web/app.js
```

Node.js 22+ 用于无依赖的前端静态 / 流解析测试。GitHub Actions 执行相同检查。

可选的真实后端浏览器验收：安装 `playwright`，在已有 Microsoft Edge 的环境运行 `python scripts/test_web.py`。它启动临时数据库与后台服务，验证登录、建组、库存、账单、画像、无密钥错误和桌面/手机布局；不会调用付费 AI。截图写入被 Git 忽略的 `exports/`。

- Python：身份与权限、群组隔离、乐观锁、事务回滚、幂等性、收据分摊、价格优先级、图片草稿、四 Agent 调度、重试、缓存、过敏原、计划隐私、内存撤回、SSE/WS、重启恢复。
- SSE：中文、emoji、CRLF 的每一种切块边界。
- 小程序：8 页文件完整性、JS 语法、JSON 和 WXML 事件处理器。**不是微信编译/真机测试**。

## 8. 部署边界

`docker compose up --build` 可启动同一套后端，持久化数据库到命名卷。Docker 容器默认关闭开发登录；容器网络客户端不一定是回环地址，正式环境使用微信认证。

当前队列有持久化任务/事件，但仅支持**一个后端 worker**。不要启动多个 Uvicorn worker。横向扩展前应迁移到 PostgreSQL + 独立任务队列，增加分布式限流、任务租约及事件保留策略。

应用重启后，中断的运行中任务标记失败并通知，避免自动重试造成用户被再次计费；尚未运行的队列任务继续处理。默认只提供站内通知，微信订阅消息需模板、用户授权与额外适配，未宣称已发送。

上线前需配置 HTTPS、备份/恢复、日志脱敏、访问控制评审、依赖扫描、数据保留与删除政策，并完成真实模型和微信测试。本仓库不构成医疗、营养认证或生产安全审计。

## Repository layout

```text
backend/app/          API, persistence, recognition, independent agents and validation
backend/data/         auditable initial USDA catalog and raw response
backend/tests/        isolated test fixtures and automated tests
miniprogram/          native WeChat mini program (8 pages)
web/                  real-API local verification console
llm_wiki/             structured knowledge, not canned model outputs
scripts/              launch, static checks and licensed-data import
.github/workflows/    CI
README.md             setup and boundaries
MealAgent_Project_Design_Document_Final_EN.md  original specification, unchanged
```
