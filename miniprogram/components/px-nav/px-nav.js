// Pixel title bar. Same API as the old glass-nav: title, subtitle, back, large + slot "right".
// `large` adds a big title plate in the page flow (with optional subtitle and right-hand slot).

// The large title shares its row with slot="right" (index: chef + avatar ≈ 260rpx, leaving ≈ 410rpx).
// Step the font down instead of cutting the name early: ≤ 7 wide chars at 56rpx, 8 at 48rpx (.long),
// then 40rpx (.xlong, about 9–10). ASCII counts as half a character; the ellipsis stays as the last resort.
function titleSizeFor(t) {
  let w = 0;
  for (const ch of String(t || '')) w += ch.charCodeAt(0) < 0x2e80 ? 0.5 : 1;
  return w <= 7 ? '' : w <= 8 ? 'long' : 'xlong';
}

Component({
  options: { multipleSlots: true },
  properties: {
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    back: { type: Boolean, value: false },
    large: { type: Boolean, value: false }
  },
  data: { statusBar: 20, barHeight: 44, total: 64, capsuleSpace: 96, titleSize: '' },
  observers: {
    title(t) { this.setData({ titleSize: titleSizeFor(t) }); }
  },
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
      this.setData({ statusBar, barHeight, total: statusBar + barHeight + 4, capsuleSpace, titleSize: titleSizeFor(this.data.title) });
    }
  },
  methods: {
    goBack() {
      wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/index/index' }) });
    }
  }
});
