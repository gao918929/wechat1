const api = require("../../utils/api");
Page({
  data: {
    personal: null,
    groupTwin: null,
    error: "",
    text: "",
    shared: false,
    visibilityIndex: 0,
    visibility: ["仅群主", "指定成员", "全员"],
    members: [],
    selectedMembers: [],
    budget: "80",
    modeIndex: 0,
    modes: ["人均预算", "总预算"],
  },
  onShow: api.guard(async function () {
    const s = await api.ready();
    if (!s) return;
    this.setData({ personal: await api.request("/twins/personal") });
    if (!s.group) return;
    this.setData({ feedback: await api.request(api.groupPath("/feedback")) });
    const settings = s.group.settings;
    this.setData({
      group: s.group,
      budget: String(settings.budget_cents / 100),
      modeIndex: settings.budget_mode === "total" ? 1 : 0,
      visibilityIndex: ["owner", "selected", "all"].indexOf(
        settings.twin_visibility,
      ),
      selectedMembers: settings.twin_members,
      members: (await api.request(api.groupPath("/members"))).map((m) => ({
        ...m,
        checked: settings.twin_members.includes(m.id),
      })),
    });
    try {
      this.setData({
        groupTwin: await api.request(api.groupPath("/twin")),
        error: "",
      });
    } catch (e) {
      this.setData({ error: e.message });
    }
  }),
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  save: api.guard(async function () {
    await api.request(api.groupPath("/feedback"), "POST", {
      action: "substitute",
      text: this.data.text,
      shared: this.data.shared,
    });
    this.setData({ text: "" });
    wx.showToast({ title: "已记录，下周学习" });
  }),
  remove: api.guard(async function (e) {
    await api.request("/feedback/" + e.currentTarget.dataset.id, "DELETE");
    await this.onShow();
  }),
  settings: api.guard(async function () {
    await api.request(api.groupPath("/settings"), "PUT", {
      budget_cents: Math.round(Number(this.data.budget) * 100),
      budget_mode: Number(this.data.modeIndex) ? "total" : "per_person",
      twin_visibility: ["owner", "selected", "all"][
        Number(this.data.visibilityIndex)
      ],
      twin_members: this.data.selectedMembers,
    });
    wx.showToast({ title: "已更新" });
  }),
});
