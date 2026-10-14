// Pixel title bar. Same API as the old glass-nav: title, subtitle, back, large + slot "right".
// `large` adds a big title plate in the page flow (with optional subtitle and right-hand slot).
Component({
  options: { multipleSlots: true },
  properties: {
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    back: { type: Boolean, value: false },
    large: { type: Boolean, value: false }
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
      } catch (e) { /* defaults */ }
      this.setData({ statusBar, barHeight, total: statusBar + barHeight + 4, capsuleSpace });
    }
  },
  methods: {
    goBack() {
      wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/index/index' }) });
    }
  }
});
