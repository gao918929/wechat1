// Frosted-glass navigation bar (iOS style) + the soft colour-mesh backdrop the glass blurs.
// Used on every page because app.json sets navigationStyle: custom.
Component({
  properties: {
    title: { type: String, value: '' },
    back: { type: Boolean, value: false }
  },
  data: { statusBar: 20, barHeight: 44, total: 64, capsuleSpace: 96 },
  lifetimes: {
    attached() {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
      const statusBar = info.statusBarHeight || 20;
      let barHeight = 44;
      let capsuleSpace = 96;
      try {
        const m = wx.getMenuButtonBoundingClientRect();
        if (m && m.height) {
          barHeight = (m.top - statusBar) * 2 + m.height;
          capsuleSpace = info.windowWidth - m.left + 8;
        }
      } catch (e) { /* use defaults */ }
      this.setData({ statusBar, barHeight, total: statusBar + barHeight, capsuleSpace });
    }
  },
  methods: {
    goBack() {
      wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/index/index' }) });
    }
  }
});
