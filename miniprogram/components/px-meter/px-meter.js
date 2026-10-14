// Segmented pixel meter (HP-bar style); filled cells pop in one by one.
//   <px-meter value="{{72}}" segments="10" color="green" />
const COLORS = ['green', 'orange', 'red', 'blue', 'purple', 'yellow'];

Component({
  properties: {
    value: { type: Number, value: 0 },        // 0–100 (values above 100 show as full + "over" style)
    segments: { type: Number, value: 10 },
    color: { type: String, value: 'green' },
    height: { type: Number, value: 28 },      // rpx
    animate: { type: Boolean, value: true }
  },
  data: { cells: [], tone: 'green', over: false },
  observers: {
    'value, segments, color': function (value, segments, color) {
      const n = Math.max(1, Math.min(40, segments || 10));
      const v = Math.max(0, value || 0);
      const lit = Math.round(Math.min(100, v) / 100 * n);
      const cells = [];
      for (let i = 0; i < n; i++) cells.push({ on: i < lit, delay: i * Math.min(45, Math.floor(600 / n)) });
      this.setData({ cells, over: v > 100, tone: COLORS.indexOf(color) >= 0 ? color : 'green' });
    }
  }
});
