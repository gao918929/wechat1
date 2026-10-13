const api = require("../../utils/api");
Page({
  data: {
    items: [],
    catalog: [],
    foodIndex: 0,
    grams: "",
    expires: api.today(2),
    estimated: false,
    price: "",
    source: "本地市场手动参考价",
    editing: null,
    busy: false,
  },
  onShow: api.guard(async function () {
    await this.load();
    this.closeLive = api.live(() => this.load().catch(() => {}));
  }),
  onHide() {
    if (this.closeLive) this.closeLive();
  },
  onUnload() {
    if (this.closeLive) this.closeLive();
  },
  async load() {
    const s = await api.ready();
    if (!s) return;
    this.setData({ catalog: s.catalog });
    if (s.group)
      this.setData({ items: await api.request(api.groupPath("/inventory")) });
  },
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  add: api.guard(async function () {
    this.setData({ busy: true });
    const food = this.data.catalog[Number(this.data.foodIndex)];
    if (!food) throw new Error("先登录");
    const body = {
      ingredient_id: food.id,
      grams: Number(this.data.grams),
      expires_on: this.data.expires,
      estimated: this.data.estimated,
    };
    if (this.data.editing) {
      const old = this.data.editing;
      Object.assign(body, {
        version: old.version,
        purchased_on: old.purchased_on,
        freshness: old.freshness,
      });
      await api.request(api.groupPath("/inventory/" + old.id), "PUT", body);
    } else await api.request(api.groupPath("/inventory"), "POST", body);
    this.setData({ grams: "", editing: null });
    await this.load();
    wx.showToast({ title: "已保存" });
  }),
  edit(e) {
    const row = this.data.items.find(
      (x) => x.id === e.currentTarget.dataset.id,
    );
    this.setData({
      editing: row,
      foodIndex: this.data.catalog.findIndex((f) => f.id === row.ingredient_id),
      grams: String(row.grams),
      expires: row.expires_on,
      estimated: row.estimated,
    });
    wx.pageScrollTo({ scrollTop: 99999 });
  },
  cancel() {
    this.setData({ editing: null, grams: "" });
  },
  consume: api.guard(async function (e) {
    const amount = await api.ask("本次使用多少克？", "请输入实际用量");
    if (amount === null) return;
    await api.request(api.groupPath("/consume"), "POST", {
      request_id: api.id(),
      items: [
        { inventory_id: e.currentTarget.dataset.id, grams: Number(amount) },
      ],
    });
    await this.load();
  }),
  discard: api.guard(async function (e) {
    const row = this.data.items.find(
      (x) => x.id === e.currentTarget.dataset.id,
    );
    const yes = await new Promise((resolve) =>
      wx.showModal({
        title: "确认丢弃 / 移除",
        content: "库存将归零。此操作不会被记作食用。",
        success: (r) => resolve(r.confirm),
      }),
    );
    if (!yes) return;
    await api.request(
      api.groupPath("/inventory/" + row.id + "?version=" + row.version),
      "DELETE",
    );
    await this.load();
  }),
  price: api.guard(async function () {
    const food = this.data.catalog[Number(this.data.foodIndex)];
    await api.request(api.groupPath("/prices"), "POST", {
      ingredient_id: food.id,
      cents_per_kg: Math.round(Number(this.data.price) * 100),
      source: this.data.source,
    });
    wx.showToast({ title: "参考价已保存" });
  }),
  photo() {
    wx.navigateTo({ url: "/pages/recognize/index?kind=inventory" });
  },
});
