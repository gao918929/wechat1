# 界面预览工具 Preview tool

在没有微信开发者工具的环境里，把小程序页面渲染成截图，用于检查设计。页面的 **真实 JS**（`Page()` 逻辑）会在桩化的
`wx` / `getApp` / `utils/api` 上运行，接口数据来自用真实后端生成的 `mockdata.json`。

```bash
pip install -r backend/requirements.txt          # 生成数据需要后端依赖
cd backend && python ../tools/preview/gen_mockdata.py && cd ..
npm i -g playwright && npx playwright install chromium   # 或使用已有的 Chromium
NODE_PATH=$(npm root -g) node tools/preview/preview.js all       # 全部页面
NODE_PATH=$(npm root -g) node tools/preview/preview.js index plan_gen
```

输出在 `tools/preview/out/`：`<name>.png` 为一屏（375×812 @2x），`<name>_full.png` 为整页。

可用名称：index、inventory、planner、budget、profile、plan_gen、plan_done、shopping、nutrition、twin、group、notifications、recognize。

## 局限

- 这是近似渲染：支持 `wx:if/elif/else`、`wx:for`、`{{}}` 表达式、自定义组件和插槽；不执行交互，也不实现原生组件的全部细节（`picker`、`switch`、`slider` 用简单占位）。
- 截图前等待 0.7 秒，入场动画会停在最后一帧；循环动画随机停在某一帧。
- 字体用后端 `backend/app/static/fonts/` 里的像素字体。

最终效果以微信开发者工具和真机为准。
