const api = require("../../utils/api");
const { SSEParser } = require("../../utils/sse");
Page({
  data: {
    prompt:
      "请根据现有库存、预算与大家的饮食约束，规划一周晚餐。优先消耗临期食材。",
    budget: "80",
    modeIndex: 0,
    modes: ["人均预算", "总预算"],
    days: "7",
    start: api.today(),
    members: [],
    diners: [],
    override: false,
    job: null,
    stage: "",
    variants: [],
    variantIndex: 0,
    selected: null,
    busy: false,
    shared: [],
    canvasHeight: 300,
  },
  onShow: api.guard(async function () {
    const s = await api.ready();
    if (!s || !s.group) return;
    const members = await api.request(api.groupPath("/members"));
    this.setData({
      members: members.map((x) => ({ ...x, checked: true })),
      diners: members.map((x) => x.id),
      budget: String(s.group.settings.budget_cents / 100),
      modeIndex: s.group.settings.budget_mode === "total" ? 1 : 0,
    });
    const jobs = await api.request(api.groupPath("/plans"));
    const active = wx.getStorageSync("activeJob");
    const job = jobs.find((j) => j.id === active) || jobs[0];
    if (job) {
      this.accept(job);
      if (["queued", "running"].includes(job.status)) this.watch(job.id);
    }
    this.setData({
      shared: await api.request(api.groupPath("/selected-plans")),
    });
    this.closeLive = api.live(() =>
      api
        .request(api.groupPath("/selected-plans"))
        .then((shared) => this.setData({ shared }))
        .catch(() => {}),
    );
  }),
  onHide() {
    if (this.closeLive) this.closeLive();
    this.stop();
  },
  onUnload() {
    if (this.closeLive) this.closeLive();
    this.stop();
  },
  stop() {
    if (this.stream) this.stream.abort();
    if (this.poll) clearInterval(this.poll);
  },
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  chooseDiners(e) {
    this.setData({ diners: e.detail.value });
  },
  generate: api.guard(async function () {
    this.setData({ busy: true });
    const job = await api.request(api.groupPath("/plans"), "POST", {
      prompt: this.data.prompt,
      budget_cents: Math.round(Number(this.data.budget) * 100),
      budget_mode: Number(this.data.modeIndex) ? "total" : "per_person",
      days: Number(this.data.days),
      start_date: this.data.start,
      diners: this.data.diners,
      override_soft: this.data.override,
      request_id: api.id(),
    });
    wx.setStorageSync("activeJob", job.id);
    this.accept(job);
    this.watch(job.id);
  }),
  accept(job) {
    const variants = job.result
      ? job.result.variants.map((v) => this.decorate(v))
      : [];
    this.setData({
      job,
      isShared: false,
      variants,
      selected: variants[0] || null,
      variantIndex: 0,
    });
  },
  decorate(v) {
    const app = getApp().globalData;
    return {
      ...v,
      cost: api.money(v.cost_cents),
      share: api.money(v.per_person_cents),
      days: v.days.map((day) => ({
        ...day,
        mine: day.nutrition_per_person[app.userId] || null,
        dishes: day.dishes.map((dish) => ({
          ...dish,
          recipientNames: dish.suitable_for.length
            ? dish.suitable_for
                .map(
                  (id) =>
                    this.data.members.find((m) => m.id === id)?.name || id,
                )
                .join("、")
            : "全员",
          ingredients: dish.ingredients.map((i) => ({
            ...i,
            displayName:
              app.catalog.find((f) => f.id === i.ingredient_id)?.name ||
              i.ingredient_id,
          })),
        })),
      })),
    };
  },
  showShared(e) {
    const row = this.data.shared.find(
      (s) => s.id === e.currentTarget.dataset.id,
    );
    if (!row) return;
    this.stop();
    const selected = this.decorate(row.plan);
    this.setData({
      job: null,
      isShared: true,
      variants: [selected],
      selected,
      variantIndex: 0,
    });
    wx.pageScrollTo({ scrollTop: 0 });
  },
  async refresh(id) {
    const job = await api.request("/plans/" + id);
    this.accept(job);
    if (!["queued", "running"].includes(job.status)) this.stop();
  },
  watch(id) {
    this.stop();
    const parser = new SSEParser((event) => {
      this.setData({
        stage:
          event.type === "stage"
            ? event.data.agent + " · " + event.data.status
            : event.type === "validation"
              ? "正在进行第 " + event.data.attempt + " 次校验修正"
              : event.type,
      });
      if (["complete", "failed", "needs_input"].includes(event.type))
        this.refresh(id).catch(() => {});
    });
    this.stream = wx.request({
      url: api.base() + "/api/plans/" + id + "/events",
      method: "GET",
      enableChunked: true,
      timeout: 600000,
      header: { Authorization: "Bearer " + getApp().globalData.token },
      fail: () => {},
    });
    if (this.stream.onChunkReceived)
      this.stream.onChunkReceived(({ data }) => parser.push(data));
    this.poll = setInterval(() => this.refresh(id).catch(() => {}), 5000);
  },
  variant(e) {
    const i = Number(e.currentTarget.dataset.index);
    this.setData({ variantIndex: i, selected: this.data.variants[i] });
  },
  select: api.guard(async function () {
    await api.request("/plans/" + this.data.job.id + "/select", "POST", {
      mode: this.data.selected.mode,
    });
    wx.showToast({ title: "已选用并共享" });
  }),
  shoppingText() {
    const v = this.data.selected;
    if (!v) throw new Error("请先选择生成完成的方案");
    return [
      v.title,
      ...v.shopping.map(
        (i) =>
          `${i.category} · ${i.name} ${i.grams}g ¥${api.money(i.cents)}${i.estimated ? " (估算)" : ""}`,
      ),
      `合计 ¥${v.cost} / 人均 ¥${v.share}`,
      v.disclaimer,
    ].join("\n");
  },
  copy: api.guard(async function () {
    wx.setClipboardData({ data: this.shoppingText() });
  }),
  image: api.guard(async function () {
    const lines = this.shoppingText()
      .split("\n")
      .flatMap((line) => line.match(/.{1,23}/g) || [""]);
    const height = 100 + lines.length * 24;
    this.setData({ canvasHeight: height });
    await new Promise((r) => setTimeout(r, 100));
    const ctx = wx.createCanvasContext("shopping", this);
    ctx.setFillStyle("#f6f7f2");
    ctx.fillRect(0, 0, 360, height);
    ctx.setFillStyle("#19372a");
    ctx.setFontSize(20);
    ctx.fillText("MealAgent · 采购清单", 20, 38);
    ctx.setFontSize(13);
    lines.forEach((line, i) => ctx.fillText(line, 20, 80 + i * 24));
    await new Promise((resolve) => ctx.draw(false, resolve));
    wx.canvasToTempFilePath(
      {
        canvasId: "shopping",
        width: 360,
        height,
        destWidth: 720,
        destHeight: height * 2,
        success: (r) => wx.previewImage({ urls: [r.tempFilePath] }),
      },
      this,
    );
  }),
});
