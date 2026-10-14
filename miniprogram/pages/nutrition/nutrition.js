const api = require('../../utils/api');
const app = getApp();

// ---- display helpers (presentation only; WXML cannot call functions) ----
// Pixel bar chart: each column is a stack of cells, 16rpx pitch (12rpx cell + 4rpx ink gap).
const ROWS = 16;          // rows in the plot
const TARGET_ROW = 12;    // the daily target sits on this row unless a day is far above it
const PITCH = 16;         // rpx per cell
// S / A / B / C rating badge (spec: ≥90 S, ≥75 A, ≥60 B, otherwise C)
const GRADES = [
  { min: 90, grade: 'S', color: 'yellow' },
  { min: 75, grade: 'A', color: 'green' },
  { min: 60, grade: 'B', color: 'blue' },
  { min: -Infinity, grade: 'C', color: 'orange' }
];
const MACRO_STYLE = {
  能量: { icon: 'flame', color: 'yellow' },
  蛋白质: { icon: 'egg', color: 'green' },
  脂肪: { icon: 'oil', color: 'orange' },
  碳水: { icon: 'meal', color: 'blue' }
};
const MACRO_HINT = { 蛋白质: '鸡蛋、豆腐或瘦肉', 脂肪: '坚果或适量用油', 碳水: '米饭或杂粮' };
const MICRO_STYLE = {
  维生素C: { icon: 'tomato', tile: 'i-red' },
  钙: { icon: 'milk', tile: 'i-blue' },
  铁: { icon: 'leaf', tile: 'i-teal' },
  食盐: { icon: 'salt', tile: 'i-yellow', limit: true }
};
const MEMBER_TONES = ['tone-green', 'tone-blue', 'tone-orange', 'tone-purple', 'tone-pink'];

function gradeOf(score) {
  if (score === null || score === undefined) return { grade: '?', color: 'green', cls: 'g-none' };
  const g = GRADES.find((x) => score >= x.min);
  return { grade: g.grade, color: g.color, cls: 'g-' + g.grade };
}

Page({
  data: { view: 'me', days: 7, report: null, bars: [], group: null, members: [], chart: null },

  onShow() { app.ready().then(() => this.load()); },

  setView(e) { this.setData({ view: e.currentTarget.dataset.v }); this.load(); },
  setDays(e) { this.setData({ days: Number(e.currentTarget.dataset.d) }); this.load(); },

  load() {
    if (this.data.view === 'group') {
      const g = app.currentGroup();
      return api.get('/api/groups/' + g.id + '/nutrition', { days: this.data.days }).then((r) => {
        r.members.forEach((m) => { m.pct = m.target_kcal ? Math.min(100, Math.round(m.avg_kcal / m.target_kcal * 100)) : 0; });
        // display: avatar initial + colour, protein meter
        r.members.forEach((m, i) => {
          m.initial = (m.nickname || '?').slice(0, 1);
          m.tone = MEMBER_TONES[i % MEMBER_TONES.length];
          m.proteinPct = m.target_protein ? Math.min(100, Math.round(m.avg_protein / m.target_protein * 100)) : 0;
          m.kcalOver = !!m.target_kcal && m.avg_kcal > m.target_kcal * 1.1;
        });
        this.setData({ group: g, members: r.members, disclaimer: r.disclaimer });
      });
    }
    return api.get('/api/me/nutrition', { days: this.data.days }).then((r) => {
      const max = Math.max(r.target.kcal * 1.3, ...r.series.map((s) => s.kcal), 1);
      const CHART = 260; // rpx
      const WEEK = ['日', '一', '二', '三', '四', '五', '六'];
      const bars = r.series.slice(-7).map((s) => ({
        date: s.date.slice(5).replace('-', '/'), week: WEEK[new Date(s.date.replace(/-/g, '/')).getDay()], kcal: s.kcal, score: s.score,
        h: Math.max(s.kcal ? 8 : 4, Math.round(s.kcal / max * CHART)), over: s.kcal > r.target.kcal * 1.1, empty: !s.kcal
      }));
      r.targetLine = Math.round(r.target.kcal / max * CHART);
      r.scoreText = r.score === null || r.score === undefined ? '—' : r.score;
      r.scoreLevel = r.score >= 85 ? '很棒' : r.score >= 70 ? '不错' : r.score >= 50 ? '需改进' : '待记录';
      const avg = r.average || {};
      const macro = (v, t) => (t ? Math.min(100, Math.round((v || 0) / t * 100)) : 0);
      r.macros = [
        { name: '能量', v: avg.kcal || 0, t: r.target.kcal, unit: 'kcal', pct: macro(avg.kcal, r.target.kcal) },
        { name: '蛋白质', v: avg.protein || 0, t: r.target.protein_g, unit: 'g', pct: macro(avg.protein, r.target.protein_g) },
        { name: '脂肪', v: avg.fat || 0, t: r.target.fat_g, unit: 'g', pct: macro(avg.fat, r.target.fat_g) },
        { name: '碳水', v: avg.carb || 0, t: r.target.carb_g, unit: 'g', pct: macro(avg.carb, r.target.carb_g) }
      ];
      const logged = r.series.filter((s) => s.kcal);
      const sum = (k) => logged.reduce((a, s) => a + s[k], 0);
      const n = logged.length || 1;
      r.micro = [
        { name: '维生素C', v: Math.round(sum('vc') / n), unit: 'mg', ref: 100 },
        { name: '钙', v: Math.round(sum('ca') / n), unit: 'mg', ref: 800 },
        { name: '铁', v: Math.round(sum('fe') / n * 10) / 10, unit: 'mg', ref: 12 },
        { name: '食盐', v: Math.round(sum('salt_g') / n * 10) / 10, unit: 'g', ref: 5 }
      ];
      r.reasons = [];
      logged.forEach((s) => s.reasons.forEach((x) => { if (r.reasons.indexOf(x) < 0) r.reasons.push(x); }));
      const chart = this.decorate(r, bars);
      this.setData({ report: r, bars, chart });
    });
  },

  // Presentation-only fields for the pixel layout (rating badge, block chart, meters, tiles, partner comment).
  decorate(r, bars) {
    const target = r.target.kcal || 0;
    const g = gradeOf(r.score);
    r.grade = g.grade;
    r.gradeColor = g.color;
    r.gradeCls = g.cls;
    r.scoreMeter = r.score || 0;

    // block chart: the target lands on TARGET_ROW unless a day needs more headroom
    const peak = Math.max(...bars.map((b) => b.kcal || 0), 0);
    const perCell = Math.max(target / TARGET_ROW, peak / ROWS, 1);
    const targetRows = target / perCell;
    bars.forEach((b) => {
      const k = b.kcal || 0;
      const count = k ? Math.max(1, Math.min(ROWS, Math.floor(k / perCell))) : 0;
      const cells = [];
      for (let i = 0; i < count; i++) cells.push(b.over && i >= Math.floor(targetRows) ? 'hot' : 'ok');
      b.cells = cells;
    });

    r.macros.forEach((m) => {
      const st = MACRO_STYLE[m.name] || { icon: 'leaf', color: 'green' };
      m.icon = st.icon;
      m.color = st.color;
    });

    r.micro.forEach((m) => {
      const st = MICRO_STYLE[m.name] || { icon: 'leaf', tile: 'i-teal' };
      const ratio = m.ref ? m.v / m.ref : 0;
      m.icon = st.icon;
      m.tile = st.tile;
      m.refLabel = st.limit ? '上限' : '参考';
      if (!r.logged_days) { m.state = '待记录'; m.stateCls = 'gray'; m.color = 'green'; }
      else if (st.limit) {
        const over = m.v > m.ref;
        m.state = over ? '超标' : '达标'; m.stateCls = over ? 'danger' : ''; m.color = over ? 'red' : 'green'; m.over = over;
      } else {
        const ok = ratio >= 0.9;
        m.state = ok ? '达标' : '偏低'; m.stateCls = ok ? '' : 'warn'; m.color = ok ? 'green' : 'orange';
      }
      // only an upper limit may exceed 100 (makes <px-meter> flash red); plenty of a nutrient is just a full bar
      m.meter = st.limit ? Math.round(ratio * 100) : Math.min(100, Math.round(ratio * 100));
    });

    // health partner's one-paragraph read-out
    const avg = r.average || {};
    if (!r.logged_days) {
      r.comment = '还没有饮食记录哦。在计划里点“吃了”，或拍照复盘一餐，我就能给你评级啦！';
    } else {
      const ratio = target ? Math.round((avg.kcal || 0) / target * 100) : 0;
      const tips = [];
      const weak = r.macros.slice(1).filter((m) => m.pct < 85).sort((a, b) => a.pct - b.pct)[0];
      if (weak) tips.push(weak.name + '偏少，多安排些' + MACRO_HINT[weak.name]);
      const salt = r.micro.find((m) => m.name === '食盐');
      if (salt && salt.over) tips.push('食盐超标，做菜少放点盐');
      r.comment = '近 ' + this.data.days + ' 天记录了 ' + r.logged_days + ' 天，日均 ' + (avg.kcal || 0) + ' kcal，约为目标的 ' + ratio + '%。'
        + (tips.length ? tips.join('；') + '。' : '三大营养素都很均衡，继续保持！');
    }

    return {
      plotH: ROWS * PITCH + 4,
      targetBottom: Math.round(targetRows * PITCH / 4) * 4
    };
  }
});
