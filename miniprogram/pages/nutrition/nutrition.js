const api = require('../../utils/api');
const app = getApp();

Page({
  data: { view: 'me', days: 7, report: null, bars: [], group: null, members: [] },

  onShow() { app.ready().then(() => this.load()); },

  setView(e) { this.setData({ view: e.currentTarget.dataset.v }); this.load(); },
  setDays(e) { this.setData({ days: Number(e.currentTarget.dataset.d) }); this.load(); },

  load() {
    if (this.data.view === 'group') {
      const g = app.currentGroup();
      return api.get('/api/groups/' + g.id + '/nutrition', { days: this.data.days }).then((r) => {
        r.members.forEach((m) => { m.pct = m.target_kcal ? Math.min(100, Math.round(m.avg_kcal / m.target_kcal * 100)) : 0; });
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
      this.setData({ report: r, bars });
    });
  }
});
