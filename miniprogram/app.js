App({
  globalData: { token: "", userId: "", group: null, catalog: [] },
  onLaunch() {
    this.globalData.token = wx.getStorageSync("token") || "";
    this.globalData.userId = wx.getStorageSync("userId") || "";
    this.globalData.group = wx.getStorageSync("group") || null;
  },
});
