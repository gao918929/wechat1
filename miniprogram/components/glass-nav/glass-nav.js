// iOS-style navigation: transparent at rest, frosted glass once content scrolls under it.
// `large` renders an iOS large title (with optional subtitle and a right-hand slot) in the
// page flow; the small centred title fades in when the large one scrolls away.
Component({
  options: { multipleSlots: true },
  properties: {
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    back: { type: Boolean, value: false },
    large: { type: Boolean, value: false }
  },
  data: { statusBar: 20, barHeight: 44, total: 64, capsuleSpace: 96, scrolled: false },
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
      this.setData({ statusBar, barHeight, total: statusBar + barHeight, capsuleSpace });
    },
    ready() {
      // The sentinel sits just below the bar (or below the large title); once it leaves the
      // visible area under the bar, content is scrolling beneath the glass.
      this.observer = this.createIntersectionObserver({ thresholds: [0, 1] })
        .relativeToViewport({ top: -this.data.total });
      this.observer.observe('.gn-sentinel', (res) => {
        const scrolled = res.intersectionRatio === 0 && res.boundingClientRect.top < this.data.total;
        if (scrolled !== this.data.scrolled) this.setData({ scrolled });
      });
    },
    detached() {
      if (this.observer) this.observer.disconnect();
    }
  },
  methods: {
    goBack() {
      wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/index/index' }) });
    }
  }
});
