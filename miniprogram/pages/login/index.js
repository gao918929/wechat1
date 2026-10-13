const api = require("../../utils/api");
Page({
  data: {
    name: "",
    key: "",
    dev: false,
    consent: false,
    base: api.base(),
    busy: false,
  },
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  toggle(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  login: api.guard(async function () {
    if (!this.data.consent) throw new Error("请先阅读并同意数据使用说明");
    if (!/^https?:\/\//.test(this.data.base))
      throw new Error("服务器地址必须以 http:// 或 https:// 开头");
    wx.setStorageSync("apiBase", this.data.base);
    this.setData({ busy: true });
    let result;
    if (this.data.dev)
      result = await api.request("/auth/dev", "POST", {
        name: this.data.name || "本地用户",
        key: this.data.key,
      });
    else {
      const code = await new Promise((resolve, reject) =>
        wx.login({ success: (r) => resolve(r.code), fail: reject }),
      );
      result = await api.request("/auth/wechat", "POST", {
        code,
        name: this.data.name || "MealAgent用户",
      });
    }
    getApp().globalData.token = result.token;
    getApp().globalData.userId = result.user_id;
    getApp().globalData.group = null;
    getApp().globalData.catalog = [];
    wx.setStorageSync("token", result.token);
    wx.setStorageSync("userId", result.user_id);
    wx.removeStorageSync("group");
    wx.navigateBack({ fail: () => wx.switchTab({ url: "/pages/home/index" }) });
  }),
});
