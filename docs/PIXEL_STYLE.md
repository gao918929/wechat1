# 像素厨房 Pixel Kitchen · 设计规范与动效提示词

MealAgent 小程序的像素风设计系统。它既是开发规范，也是驱动“画师 / 页面 / 评审”智能体的提示词。
**改任何页面前先读完本文件。**

---

## 1. 概念

**一句话**：一款温馨的 8-bit 料理经营游戏——番茄小厨带着四位智能体伙伴（健康 / 迭代 / 库存 / 预算），帮宿舍和家庭打理一周的饭。

- **游戏化隐喻**：卡片是“游戏窗口”，进度是“血条”，计划生成是“伙伴组队作战”，入库是“获得物品”，评分是“星星”，营养评分是“S/A/B/C 评级”。
- **温馨不刺眼**：奶油纸色网格背景 + 墨紫描边 + 有限的 26 色调色板。不要霓虹，不要大面积纯黑。
- **信息依然优先**：游戏感是包装，核心数据（价格、热量、到期天数）必须一眼可读。

## 2. 像素网格与基础规则

| 规则 | 值 |
|---|---|
| 1 个“美术像素” | `4rpx`（`--px`）。所有尺寸、边距、阴影都按 4rpx 的倍数 |
| 圆角 | **禁止**（`border-radius` 一律不用）。缺角像素边框用 4 个 `box-shadow` 画 |
| 阴影 | 只用**硬阴影**（模糊半径 0）：`8rpx 12rpx 0 0 var(--shadow)` |
| 渐变 | 禁止柔和渐变；只允许像素条纹（`repeating-linear-gradient` 硬色阶） |
| 模糊 / 毛玻璃 | 禁止（`backdrop-filter`、`filter: blur`） |
| 字号 | 20 / 24 / 28 / 32 / 40 / 48 / 56rpx |
| 字体 | 正文与标题 `"Pixel"`（Fusion Pixel 12px）；价格与数字用 `.px-num`（Press Start 2P，很宽：每个字符约等于字号宽度，超过 7 个字符时降到 24rpx） |

缺角描边的标准写法（与 `app.wxss` 中 `.card` 一致）：

```css
box-shadow:
  0 -4rpx 0 0 var(--ink), 0 4rpx 0 0 var(--ink), -4rpx 0 0 0 var(--ink), 4rpx 0 0 0 var(--ink), /* 描边 */
  inset -4rpx -4rpx 0 0 var(--paper-3), inset 4rpx 4rpx 0 0 #fff,                                  /* 斜面光影 */
  8rpx 12rpx 0 0 var(--shadow);                                                                    /* 硬阴影 */
```

描边会向外长 4rpx，所以带描边的元素要留 `margin: 4rpx` 以上，避免被裁切或互相贴住。

## 3. 调色板

CSS 变量见 `app.wxss`；像素画字符代码见 `tools/pixelart.py` 中的 `PALETTE`（两者一致）。

| 用途 | 变量 | 色值 | 像素画代码 |
|---|---|---|---|
| 描边墨色 | `--ink` | `#2b2340` | `K` |
| 柔和墨色 | `--ink-2` | `#4a3f6b` | `k` |
| 纸 / 纸影 / 深纸影 | `--paper` / `--paper-2` / `--paper-3` | `#fffaf0` / `#f3e9d2` / `#e2d3b1` | `w` / – / `q` |
| 背景 | `--bg` | `#f4ecd8` + 32rpx 网格 | – |
| 叶绿 / 深 / 浅 | `--green` / `-d` / `-l` | `#4cb963` / `#2e7d46` / `#a6e88a` | `g` / `G` / `l` |
| 番茄红 / 深 / 浅 | `--red` / `-d` / `-l` | `#e8553e` / `#a8322a` / `#ffb3a1` | `r` / `R` / `p` |
| 胡萝卜橙 / 深 | `--orange` / `-d` | `#f59a2c` / `#b8641b` | `o` / `O` |
| 黄油黄 / 深 | `--yellow` / `-d` | `#f8d24b` / `#c79a1e` | `y` / `Y` |
| 天蓝 / 深 / 冰 | `--blue` / `-d` / `-l` | `#4fa8e0` / `#2d6fa8` / `#b5e1ff` | `b` / `B` / `c` |
| 葡萄紫 / 深 | `--purple` / `-d` | `#8e6ad8` / `#5b3fa0` | `v` / `V` |
| 粉 | `--pink` | `#f27ba6` | `m` |
| 棕 / 深棕 / 肤色 / 灰 / 深灰 | – | `#9b6a3c` / `#5e3d22` / `#ffd2a8` / `#c9c3d6` / `#8a8199` | `n` / `N` / `s` / `e` / `E` |

**语义色**：绿 = 健康 / 新鲜 / 完成；橙 = 临期 / 提醒；红 = 过期 / 超预算 / 硬约束；蓝 = 信息 / 水产；黄 = 选中 / 奖励；紫 = AI / 智能。

## 4. 组件（“插件”）

所有组件都已在 `app.json` 全局注册。

### `<px-nav>` 像素标题栏（替换旧的 `<glass-nav>`，API 相同）

```xml
<px-nav title="冰箱" subtitle="302 宿舍 · 7 种食材" large back>
  <view slot="right">…右侧按钮或精灵…</view>
</px-nav>
```

- `title`、`subtitle`、`back`（返回箭头）、`large`（页面内大标题牌，带纸影投影字）、`slot="right"`。
- tab 页用 `large`，二级页用 `back`。
- 大标题按字数自动降一档字号，不会过早截断（组件 JS 按标题宽度算 `titleSize`，中文算 1 个字，ASCII 算半个）：≤ 7 个字 56rpx；8 个字 `.long` 48rpx；更长 `.xlong` 40rpx（约 9–10 个字），再长才出现省略号。行高固定，标题牌不会跳动。阈值按首页右侧插槽（小厨 + 头像，约 260rpx）定的。

### `<px-sprite>` 像素角色动画

```xml
<px-sprite name="sprite-chef" frames="4" size="120" duration="800" />
```

逐帧播放 `/assets/px/<name>.svg` 精灵表（各帧从左到右排列）。`size` 是单帧宽度（rpx），`height` 默认等于 `size`，`playing="{{false}}"` 可暂停。

### `<px-meter>` 分段血条

```xml
<px-meter value="{{72}}" segments="10" color="green" height="28" />
```

`color` 可选 green / orange / red / blue / purple / yellow。点亮的格子逐格弹入；`value > 100` 时整条红色闪烁（超标 / 超预算）。

### `<px-typewriter>` RPG 打字机文字

```xml
<px-typewriter text="{{summary}}" speed="30" step="2" />
```

逐字显示，结束后闪烁 ▼。点击立即显示全文。用于智能体结论、对话回复、提示语。`instant` 可关闭动画。

### 全局 CSS 类（`app.wxss`）

| 类 | 说明 |
|---|---|
| `.container`（`.no-tab`） | 页面容器；默认底部留出标签栏的 220rpx，二级页（没有标签栏）加 `.no-tab`，只留 80rpx + 安全区 |
| `.card`（`.flush` / `.hero` / `.feature` + `.blue` / `.orange` / `.purple` / `.red`） | 像素窗口；`feature` 是彩色状态窗口（白字）；`.feature.red` 用于失败 / 超预算 / 错误 |
| `.px-dialog` | 深色 RPG 对话框（双描边，`position: relative`，可直接放 `.name-plate`） |
| `.win-tab` + `.win-tab-icon` | 窗口上沿的黄色名牌：`<view class="win-tab"><image class="win-tab-icon" src="/assets/px/flame.svg" />今日能量</view>`。放在 `.card` 里；窗口上内边距约 40rpx、上外边距 ≥ 36rpx，名牌才不压到上方内容 |
| `.name-plate`（`.green` / `.purple`） | 对话框说话人名牌（纯文字，默认黄色）；父元素需 `position: relative`（`.card`、`.px-dialog` 已是） |
| `.section-title` | ▶ 分区标题；右侧 `.link`（绿色，可点）或 `.sec-hint`（灰色说明，不可点） |
| `.btn`（`.ghost` / `.warn` / `.danger` / `.small`）+ `.btn-icon` | 像素按钮，**必须加** `hover-class="px-pressed"`（按下下沉）；按钮图标 32rpx |
| `.px-pressed-row` | 窗口内列表行的轻按下态（纸影底 + 顶部内阴影，无墨色描边、不位移）：菜单行、选择器行、名单行、流水行用 `hover-class="px-pressed-row"`；独立的按钮 / 卡片仍用 `px-pressed` |
| `.tag`（`.warn` / `.danger` / `.gray` / `.blue` / `.glass` / `.gold` / `.purple`） | 像素徽章；`.gold` = 管理员 / 奖励，`.purple` = AI / 孪生 |
| `.est-badge` | 估算值后面的橙色小“估算”徽章 |
| `.chip`、`.chips` | 横向像素胶囊 |
| `.input`、`.textarea`、`.field`、`.chat-bar`、`.send` | 凹陷输入框 |
| `.px-toggle`（`.on`）+ `.px-toggle-knob` + `.px-toggle-txt` | 像素 ON / OFF 开关（原生 `<switch>` 是圆的）：`<view class="px-toggle {{on ? 'on' : ''}}" bindtap="…" hover-class="px-pressed"><view class="px-toggle-knob"></view><text class="px-num px-toggle-txt">{{on ? 'ON' : 'OFF'}}</text></view>`，旋钮逐格滑动 |
| `.px-cal` + `.px-cal-top` + `.px-num .px-cal-day`（`.sm`） | 日历日期牌：红色顶条（月份或星期）+ 大号像素日期；`.sm` 是紧凑版 |
| `.px-led`（`.on` 绿 / `.red` 红 / 默认灰；`.sm` 12rpx）+ `.px-led-core` | 状态灯：墨色灯框固定不动，只让灯芯闪（把 `.anim-blink` 加在 `.px-led-core` 上，不要加在灯框上，否则描边也会消失） |
| `.avatar` | 方形像素头像（颜色用下面的颜色工具类） |
| `.cat-<分区>` | 食材分区色块：`vegetables` 绿、`meat_eggs` 红、`seafood` 蓝、`staples` 黄（墨色字）、`soy_dairy` 紫、`seasonings` 灰紫、`other` 浅灰（墨色字）。冰箱 / 识别的首字头像、购物清单分区条、账本构成条与图例共用 |
| `.agent-health` / `-iterative` / `-inventory` / `-budget` | 四位智能体精灵格的浅色底（绿 / 紫 / 蓝 / 粉） |
| `.tone-green` / `-blue` / `-orange` / `-purple` / `-pink` | 成员头像轮换色（小组名单、营养小组视图） |
| `.grid` / `.grid-item .icon`、`.mini-icon` + `.i-blue` / `-orange` / `-purple` / `-pink` / `-teal` / `-yellow` / `-red` | 图标格；`.mini-icon` 是 64rpx 格 + 48rpx 图标 |
| `.check` / `.check.on` | 像素复选框（带像素对勾） |
| `.tabs .tab.active` | 像素页签（选中抬起变黄） |
| `.bar .fill` | 静态像素条（动画请用 `<px-meter>`） |
| `.stat .num .lbl`、`.px-num`、`.px-num.inline` | 数字统计；`.px-num.inline` 把夹在中文里的 20–24rpx 像素数字下移 4rpx，对齐中文基线 |
| `.px-loading` | 行进条纹加载条 |
| `.mask` + `.sheet`、`.sheet-close` | 底部弹出窗口（像素滑入）；`.sheet-close` 是标题栏右侧的方形关闭键（内放 32rpx `cross` 图标） |

**尺寸约定**：全局文字只用 20 / 24 / 28 / 32rpx（24rpx = 字体原生 12px，最清晰；`.tag`、`.notice`、`.small`、`.tabs .tab`、`.chip-sub`、`.stat .lbl`、`.empty` 都是 24rpx，`.btn` 32rpx）。16px 图标只用 16 的倍数显示：32rpx（1:1）、48rpx、64rpx；8px 的 `ui-next` 用 16rpx，12px 的 `ui-back` 用 24 / 48rpx。

### 共享 JS 工具（`utils/util.js`）

| 函数 | 说明 |
|---|---|
| `iconFor(name)` | 食材 / 菜名 → 像素图标名（`/assets/px/<icon>.svg`），没有对应图标时返回 `''`。规则表 `ICON_RULES`：名字里**最早出现**的关键词胜出（番茄炒蛋 → tomato，鸡蛋 → egg），同一位置时**更长**的关键词胜出（油菜 → cabbage，米粉 → noodle）。图标为 `''` 的“拦截规则”专门挡住会误配的词（酱油 / 蚝油 / 玉米 / 花生 / 面包 / 面粉 / 蛋糕…）。新增食材图标时只改这张表 |
| `initialOf(name)` | 没有图标时首字头像用的字，跳过“大 / 小”前缀（大白菜 → 白，大米 → 米） |
| `metaLabel(kind, key, fallback)` / `metaLabels(kind, keys)` | 把 `app.globalData.meta` 里的选项 key 转成中文（`metaLabel('avoid_options', 'spicy')` → 辣；`kind` 可以是 `allergen_options`、`avoid_options`、`goals`、`activity_levels` 等）。找不到时返回 `fallback`，默认原样返回 key |

## 5. 动效规范与提示词

所有动效都是**逐格**的（`steps()` 或 0–49% / 50–100% 硬切），模仿 8-bit 游戏的帧动画。以下每条既是规范，也是给智能体的“动效提示词”。

| 类名 | 提示词 | 用在哪里 |
|---|---|---|
| `anim-slide` + `d1…d6` | 【入场·逐格上滑】列表项从下方 40rpx 处分 4 帧跳入，每项延迟 60ms，**最多给前 6 项**加延迟；像游戏菜单一项项展开 | 卡片、列表行、宫格 |
| `anim-slide-x` | 【入场·侧滑】从左侧 32rpx 处 4 帧滑入 | 对话框里的日志行、聊天回复 |
| `anim-pop` | 【弹出·获得物品】0.4 → 1.12 → 0.94 → 1 四帧放大回弹 | 新徽章、完成状态、“获得物品!”、选中星星 |
| `anim-bob` | 【待机·上下浮动】两帧上下 6rpx，0.8s 一循环 | 选中的标签栏图标、吉祥物、“下一步”箭头 |
| `anim-blink` / `pulse` | 【闪烁】0.5s 亮 / 0.5s 灭 | 光标、在线灯、未读红点、“思考中…” |
| `anim-shake` | 【警告·抖动】左右 6rpx 抖 2 次 | 今天到期、超预算、校验未通过（只抖一次，不要循环） |
| `anim-coin` | 【金币旋转】scaleX 1 → 0.5 → 0.1 → 0.5 → 1 四帧 | 金币图标、预算 / 价格 |
| `anim-wiggle` | 【摇摆】±8° 四帧 | 铃铛（有新通知时）、提醒图标 |
| `anim-float` | 【飘字】上升 48rpx 并消失 | “+1”“已收藏”“-¥12” 之类的即时反馈 |
| `.px-loading` | 【行进条纹】条纹 4 帧向右行进 | 生成中、上传识别中 |
| `<px-meter>` 弹入 | 【血条充能】格子逐个 2 帧弹入，间隔 45ms | 热量、预算、新鲜度、营养素 |
| `<px-typewriter>` | 【打字机】每 30ms 出 2 个字，结束闪 ▼ | 智能体结论、对话回复 |
| `<px-sprite>` | 【角色待机】2–4 帧循环 | 吉祥物、四位智能体、煮锅加载、金币 |
| `hover-class="px-pressed"` | 【按下】下沉 4×6rpx，硬阴影消失 | 所有可点按钮、卡片入口 |

**节制原则**：一屏内持续循环的动画不超过 3 个（精灵、在线灯、选中图标）；入场动画只播一次；警告抖动只在需要注意时出现。

## 6. 美术资源清单（画师提示词）

源文件放在 `art/pixel/<name>.txt`，用 `python tools/pixelart.py <name…> --sheet /tmp/x.png` 生成 SVG（输出到 `miniprogram/assets/px/`）和总览图。

**通用画法要求**：

- 1 像素墨色 `K` 外描边；
- 左上受光（高光 `W`、浅色），右下用深色阴影；
- 主体居中，四周留 1 像素透明边；
- 每个图标最多 5–6 种颜色，形状一眼可认；
- 参照 `art/pixel/tomato.txt`。

### 6.1 标签栏图标（16×16，`# variants: off` 自动生成灰色未选中版）

| 名称 | 提示词 |
|---|---|
| `tab-home` | 小木屋：红色三角屋顶（r/R）、奶油色墙（w/q）、棕色门（n/N）、一扇小窗（c） |
| `tab-fridge` | 双门冰箱：浅蓝白机身（c / w，阴影 b）、上下两门之间一条墨线、两个短把手（E） |
| `tab-plan` | 打开的食谱书或卷轴，右上角一颗黄色闪光星（y / W），表示 AI 计划 |
| `tab-wallet` | 棕色钱袋或钱包，露出一枚金币（y / Y）；袋口系绳 |
| `tab-me` | 戴白色厨师帽的圆脸小人头像（帽 w / q，脸 s，腮红 p） |

### 6.2 功能图标（16×16）

| 名称 | 提示词 |
|---|---|
| `camera` | 复古相机：深灰机身（k / E）、大圆镜头（B / b 加高光）、右上小红灯 |
| `receipt` | 竖长小票：纸色（w / q）、底部锯齿、三条灰色文字横线、一条红色合计线 |
| `meal` | 一碗米饭：蓝白瓷碗（c / b）、白色米饭堆、一双斜插的棕色筷子、两缕蒸汽 |
| `magic` | 紫色魔法棒（v / V）斜放，顶端黄色五角星（y），周围 2–3 个小闪点（W） |
| `cart` | 购物车：灰框（E / k）、车里露出绿色蔬菜和红色番茄、两个轮子 |
| `chart` | 三根高低不同的柱子（绿 / 蓝 / 橙），底部墨色基线 |
| `twin` | 数字孪生：两个面对面、一绿一紫的小人头剪影，中间一颗小红心 |
| `users` | 两个并排的小人（一个绿衣、一个蓝衣），后面那个稍高 |
| `bell` | 金色铃铛（y / Y），底部小铃舌，左上高光 |
| `heart` | 红色像素爱心（r / R），左上白色高光 |
| `loop` | 两个首尾相接的绿色环形箭头（g / G），循环 / 迭代 |
| `coin` | 正面金币：圆形（y / Y）、中间深黄“¥”字、左上高光 |
| `send` | 纸飞机：白色（w / q）、墨描边，向右上飞 |
| `plus` | 绿色粗加号（g / G 带高光），无底板 |
| `check` | 绿色粗对勾（g / G） |
| `cross` | 红色粗叉（r / R） |
| `warn` | 黄色警告三角（y / Y），中间墨色感叹号 |
| `clock` | 红色闹钟：两个铃耳、白色表盘、墨色指针（临期） |
| `scale` | 厨房秤：浅灰托盘、表盘、红色指针（重量） |
| `star` | 黄色五角星（y / Y，左上高光）；`# variants: off` |
| `trophy` | 金色奖杯，两只耳把、底座 |
| `shield` | 红白盾牌，中间白色十字（过敏原 / 硬约束） |
| `calendar` | 日历页：红色顶边、两个挂环、白色页面上几个格子 |
| `leaf` | 一片绿叶（g / G / l），中间叶脉 |
| `flame` | 火焰（外 r、中 o、内 y） |
| `egg` | 白色鸡蛋（w / q 阴影）、左上高光 |
| `meat` | 烤鸡腿：棕红肉（n / N / o 高光）、白色骨头 |
| `fish` | 蓝色小鱼（b / B / c），一只眼睛，尾巴分叉 |
| `carrot` | 橙色胡萝卜（o / O）斜放，顶部绿叶（g / G） |
| `broccoli` | 西兰花：深浅绿花冠（g / G / l）、浅绿茎 |
| `milk` | 牛奶盒：白蓝相间（w / c / b），尖顶 |
| `chili` | 红辣椒（r / R）弯曲，顶部绿蒂（不吃辣 / 辣度） |
| `cabbage` | 叶菜（白菜 / 青菜 / 菠菜 / 生菜 / 油菜）：直立的大白菜头，上半部褶皱绿叶（g / G，左上 l 受光），下半部白色菜帮（w / q）带浅绿叶脉（l）；矮胖桶形，别画成西兰花的“树冠 + 细茎” |
| `rice` | 大米：白色米袋（w / q 阴影）印红色“米”字（r），翻边袋口（q / n），袋口露出一堆白米（W / w）；不要画成碗，避免与 `meal` 混淆 |
| `tofu` | 豆腐：3/4 视角的扁方块（顶面 w + W 高光、正面 w、侧面 q，面与面之间墨线），顶上几粒葱花（g），放在蓝色浅碟（b）上 |
| `salt` | 盐：盐罐，圆顶灰盖（e / E）上一排三个墨色小孔（别排成“两只眼睛”），玻璃瓶身上部冰蓝（c）、下部白盐（w），右上飘几粒盐（W） |
| `oil` | 食用油：金黄油瓶（y / Y），左侧白色高光条（W），细瓶颈、红色小瓶盖（r / R） |
| `potato` | 土豆：横放的疙瘩椭圆（n，右下 N 阴影），左上橙色受光（o）和 W 高光，几个深棕芽眼（N） |
| `mushroom` | 蘑菇：棕色圆伞盖（n / N）带奶白斑点（w），下沿一排浅色菌褶（q），粗短奶白菌柄（w / q） |
| `shrimp` | 虾 / 海鲜：C 形弯曲的熟虾（o / r / R），深红分节线，头在右上带墨色眼睛和一根触须，尾端像鱼尾一样分叉成扇形 |
| `noodle` | 面条：红碗（r / R）带一圈黄色圆点花纹（y），碗里黄面条（y / Y 斜纹），一双筷子（N）夹起一缕面；与蓝碗米饭 `meal` 区分 |
| `apple` | 水果：红苹果（r / R，左上 W 高光），顶部凹窝伸出棕色果柄（n），旁边一片绿叶（g）；与带绿萼的 `tomato` 区分 |
| `pot` | 汤锅：灰色锅身（E / e）、两只把手、锅盖、蒸汽 |

### 6.3 角色精灵（各帧从左到右排列，帧间用 `---` 分隔，`# kind: sprite`）

| 名称 | 尺寸 × 帧 | 提示词 |
|---|---|---|
| `sprite-chef` | 24×24 × 4 | **吉祥物“番茄小厨”**：番茄身体（r / R + 高光）戴白色厨师帽（w / q），豆豆眼、腮红（p），双手拿木勺。帧 1–2 上下浮动 1 像素；帧 3 眨眼；帧 4 举勺 |
| `sprite-health` | 24×24 × 2 | **健康适配·西兰花医生**：西兰花脑袋（g / G / l），额头反光镜，胸前白底红十字；帧 2 点头（下移 1 像素） |
| `sprite-iterative` | 24×24 × 2 | **迭代优化·小机器人**：紫色方块机器人（v / V），屏幕脸上两只发光眼（c），头顶天线顶端是循环箭头；帧 2 天线灯变黄、眼睛眨 |
| `sprite-inventory` | 24×24 × 2 | **库存优先·冰箱宝宝**：浅蓝白冰箱（c / w / b），门上有一双眼睛和微笑；帧 2 门微开，露出里面的番茄和鸡蛋 |
| `sprite-budget` | 24×24 × 2 | **预算约束·存钱猪**：粉色小猪存钱罐（m / p），背上投币口；帧 1 一枚金币在上方，帧 2 金币落进投币口 |
| `sprite-pot` | 16×16 × 4 | **煮锅加载动画**：灰色汤锅，锅盖随帧轻跳，蒸汽两缕依次升起 |
| `sprite-coin` | 12×12 × 4 | **旋转金币**：正面圆 → 椭圆 → 侧面细条 → 椭圆 |
| `sprite-sparkle` | 16×16 × 4 | **闪光**：中心十字星由小到大再到小，配合周围 2 个小点闪烁（W / y） |

## 7. 页面设计方向（页面提示词）

| 页面 | 方向 |
|---|---|
| 首页 `index` | 大标题问候 + 右侧 `sprite-chef`；“今日能量”做成 RPG 状态窗：大号 `px-num` 热量 + `px-meter` 主条 + 蛋白质 / 碳水 / 脂肪三根小血条（绿 / 蓝 / 橙）；6 个快捷入口用彩色图标格（camera / receipt / meal / magic / cart / chart）逐格入场；临期胶囊带 `clock` 图标，今天到期的胶囊抖动；本周计划用绿色 `feature` 窗口加 `coin` 图标 |
| 冰箱 `inventory` | 食材行像“背包格子”：有对应食材图标就用图标（egg / tomato / meat / fish / carrot / broccoli / milk），没有就用分类色首字头像；新鲜度用 8 格 `px-meter`（按状态绿 / 橙 / 红）；临期行的天数加 `warn` 图标并抖动；聊天回复用 `px-typewriter`；数量 < 1 或带小数时只显示克数，不要出现“0.34 个” |
| AI 计划 `planner` | “接任务”界面：吉祥物和 `px-dialog` 对话框“告诉小厨你们的情况”；示例做成任务卡（quest card）；选项是像素列表；开始按钮用 `magic` 图标 + 按下效果；历史计划是任务日志（状态徽章） |
| 计划 `plan` | **生成中** = 组队作战画面：四位智能体精灵站成 2×2 小队，每人有名牌、状态（“思考中…”闪烁 →“完成!” 弹出），结论用 `px-typewriter`；`.px-loading` 进度条；协作过程用深色 `px-dialog` 日志。**结果** = 方案页签；绿色总结窗口（`px-num` 金额 + 预算血条）；每天一张卡（日历样式日期牌），菜品行用分类色块；评分用 `star` 图标，选中时弹出；四位智能体小头像 + 结论 |
| 识别 `recognize` | “获得物品”界面：清单条目像道具格，估算值带 `scale` 图标与“估算”徽章，待确认条目闪烁；编辑用像素底部弹窗；确认成功后弹出“获得物品!” |
| 购物 `shopping` | 任务清单：`feature` 窗口显示合计（`cart` + `coin`）；每个分区一个窗口，像素复选框，勾掉的条目划线变灰 |
| 账本 `budget` | 金币主题：支出总额 `px-num` + 预算 `px-meter`（超支红闪）+ 旋转金币；支出构成用像素色块条加方块图例；流水行用 `receipt` / `coin` 图标 |
| 营养 `nutrition` | 评分做成 S / A / B / C 评级大徽章（≥90 S，≥75 A，≥60 B，否则 C）；能量趋势用像素方块柱（每根柱由格子堆叠）加目标虚线；三大营养素用血条；维生素矿物质用图标格 |
| 我的 `profile` | 角色卡：吉祥物头像 + 名字 + 目标；每日目标像 RPG 属性面板；菜单行用像素图标（twin / users / chart / bell） |
| 小组 `group` | 队伍名单：成员头像、管理员戴 `trophy`/皇冠徽章；邀请码做成“暗号”框（`px-num`） |
| 数字孪生 `twin` | “记忆图鉴”：偏好、替换习惯、估重校准用像素徽章和小图标 |
| 通知 `notifications` | 信箱：`bell` 图标，未读红点闪烁，条目逐格入场 |

## 8. 小程序技术约束（必须遵守）

- **WXML 表达式里不能调用函数**（`.join()`、`.map()`、`toFixed()` 都不行），需要的字符串在 JS 里先算好；只能用数据、运算符、三元表达式。
- WXSS 的 `background-image` **只能用渐变**，不能 `url()` 本地图片；图片一律用 `<image src="/assets/px/x.svg">`。
- 不支持 `:hover`；按下效果用 `hover-class`。
- 不要用 `*` 选择器和标签选择器做布局（用 class）。
- 自定义组件已全局注册，直接用，不要在页面 json 里重复注册。
- 保留页面原有的所有业务逻辑和事件处理函数（`bindtap` 对应的方法），只改表现层。为了显示可以在 JS 里加计算字段，**不要改接口调用**。
- 页面只改自己目录下的 `.wxml` / `.wxss` / `.js` / `.json`；全局文件（`app.wxss`、组件、`app.json`、`tools`、`art`）需要改时，写进返回结果里由主控统一处理。

## 9. 预览与验收

```bash
# 生成模拟数据（只需一次）
cd backend && python ../tools/preview/gen_mockdata.py
# 截图（NODE_PATH 指向全局安装的 playwright）
NODE_PATH=/opt/node22/lib/node_modules node tools/preview/preview.js index plan_gen plan_done
# 结果：tools/preview/out/<name>.png（一屏）和 <name>_full.png（整页）
```

预览名称：index、inventory、planner、plan_gen、plan_done、recognize、shopping、budget、nutrition、profile、group、twin、notifications。

**验收清单**：

- 第一眼就是像素游戏的感觉；
- 没有圆角、柔和阴影、柔和渐变、模糊；
- 文字清楚，数字没有溢出或截断；
- 留白充足，描边没有被裁掉；
- 动效符合第 5 节，并且节制；
- 所有原功能入口都还在；
- WXML 没有函数调用；
- 与其他页面风格一致。

预览说明：这个浏览器渲染器只是近似效果（入场动画截图时已停在最后一帧），最终以微信开发者工具为准。
