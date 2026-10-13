const api = require("../../utils/api");
Page({
  data: {
    groups: [],
    group: null,
    stock: 0,
    alerts: 0,
    spent: "0.00",
    notes: [],
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
    const state = await api.ready();
    if (!state) return;
    this.setData(state);
    if (!state.group) return;
    const [stock, report, notes] = await Promise.all([
      api.request(api.groupPath("/inventory")),
      api.request(api.groupPath("/reports")),
      api.request("/notifications"),
    ]);
    this.setData({
      stock: stock.length,
      alerts: stock.filter((x) => x.alert !== "normal").length,
      spent: api.money(report.paid_cents),
      notes: notes.filter((x) => !x.read),
    });
  },
  create: api.guard(async function () {
    const name = await api.ask("创建家庭 / 宿舍", "例如：向阳四人间");
    if (!name) return;
    const group = await api.request("/groups", "POST", { name });
    getApp().globalData.group = group;
    wx.setStorageSync("group", group);
    await this.load();
    wx.showModal({
      title: "邀请成员",
      content: "邀请码：" + group.invite_code,
      confirmText: "复制",
      success: (r) => {
        if (r.confirm) wx.setClipboardData({ data: group.invite_code });
      },
    });
  }),
  join: api.guard(async function () {
    const code = await api.ask("加入群组", "粘贴邀请码");
    if (!code) return;
    const group = await api.request("/groups/join", "POST", { code });
    getApp().globalData.group = group;
    await this.load();
  }),
  switchGroup: api.guard(async function (e) {
    const group = this.data.groups[Number(e.detail.value)];
    getApp().globalData.group = group;
    wx.setStorageSync("group", group);
    if (this.closeLive) this.closeLive();
    await this.load();
    this.closeLive = api.live(() => this.load().catch(() => {}));
  }),
  open(e) {
    wx.switchTab({ url: "/pages/" + e.currentTarget.dataset.page + "/index" });
  },
  recognize(e) {
    wx.navigateTo({
      url: "/pages/recognize/index?kind=" + e.currentTarget.dataset.kind,
    });
  },
  note: api.guard(async function (e) {
    const n = this.data.notes.find((x) => x.id === e.currentTarget.dataset.id);
    await api.request("/notifications/" + n.id + "/read", "POST", {});
    wx.setStorageSync("activeJob", n.job_id);
    wx.switchTab({ url: "/pages/plan/index" });
  }),
});
