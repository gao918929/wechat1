const api = require('../../utils/api');
const app = getApp();

const WEEK = ['日', '一', '二', '三', '四', '五', '六'];

function greeting() {
  const h = new Date().getHours();
  if (h < 5) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function pct(v, t) {
  return t ? Math.max(0, Math.min(100, Math.round((v || 0) / t * 100))) : 0;
}

// ---- display helpers (presentation only; WXML cannot call functions)

// near-expiry chips: label, colour tone, pixel icon, and whether it expires today (shake once)
function decorateAlert(a, i) {
  const near = a.level === 'near_expiry';
  const soon = near && a.days_left > 0;
  return Object.assign({}, a, {
    sub: !near ? a.label : (soon ? '剩 ' + a.days_left + ' 天' : '今天到期'),
    tone: soon ? 'warn' : 'danger',
    icon: near ? 'clock' : 'warn',
    urgent: near && !soon,
    delay: i < 6 ? 'd' + (i + 1) : ''
  });
}

function nameList(list) {
  const names = list.slice(0, 2).map((a) => a.name).join('、');
  return list.length > 2 ? names + ' 等 ' + list.length + ' 样' : names;
}

// one-line advice from the mascot, built from the data already on screen
function chefTip(alerts, today, plan) {
  const near = alerts.filter((a) => a.level === 'near_expiry');
  const todayExp = near.filter((a) => !(a.days_left > 0));
  if (todayExp.length) return nameList(todayExp) + '今天到期，今晚先把它做掉吧！';
  if (near.length) {
    const min = Math.min.apply(null, near.map((a) => a.days_left));
    return nameList(near) + (min <= 1 ? '明天就到期' : min + ' 天内到期') + '，优先安排进下一餐吧。';
  }
  const stale = alerts.filter((a) => a.level !== 'near_expiry');
  if (stale.length) return nameList(stale) + '看起来不太新鲜，做饭前检查一下哦。';
  if (today && today.over) return '今天的能量已经超标啦，下一餐清淡一点吧。';
  if (!plan) return '告诉我你们的情况，我来排一周的菜单！';
  return '今天还可以吃 ' + (today ? today.left : 0) + ' kcal，按计划来就好。';
}

// budget meter for the plan window: % of budget used (>100 makes <px-meter> flash red)
// PixelNum glyphs are ~1em wide, so long amounts step down a size instead of overflowing
function numSize(v, long, longer) {
  const n = ('¥' + v).length;
  return n > longer ? 'is-s' : n > long ? 'is-m' : '';
}

function planMeta(plan) {
  const s = plan && plan.summary;
  if (!s) return { budgetPct: -1, over: false, totalSize: '', ppSize: '' };
  let util = typeof s.budget_utilization === 'number' ? s.budget_utilization : null;
  if (util === null && s.budget_total) util = (s.total_cost || 0) / s.budget_total;
  return {
    budgetPct: util === null ? -1 : Math.round(util * 100),
    over: s.within_budget === false,
    totalSize: numSize(s.total_cost, 7, 9),
    ppSize: numSize(s.per_person_cost, 7, 7)
  };
}

Page({
  data: {
    title: '',
    dateText: '',
    initial: '我',
    groups: [],
    groupIndex: 0,
    group: null,
    alerts: [],
    latestPlan: null,
    unread: 0,
    llmOnline: false,
    today: null,
    loading: true,
    // display-only
    tip: '',
    planMeta: { budgetPct: -1, over: false, totalSize: '', ppSize: '' }
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) this.getTabBar().setData({ selected: 0 });
    const d = new Date();
    this.setData({ dateText: (d.getMonth() + 1) + '月' + d.getDate() + '日 星期' + WEEK[d.getDay()] });
    app.ready().then(() => this.load());
    if (!this.off) this.off = app.onSocket((ev) => { if (ev.type === 'inventory.updated' || ev.type === 'plan.ready') this.load(); });
  },

  onUnload() { if (this.off) this.off(); },

  onPullDownRefresh() {
    this.load().then(() => wx.stopPullDownRefresh());
  },

  load() {
    const groups = app.globalData.groups;
    const group = app.currentGroup();
    const user = app.globalData.user || {};
    if (!group) return Promise.resolve();
    this.setData({
      title: greeting() + '，' + (user.nickname || '朋友'),
      initial: (user.nickname || '我').slice(0, 1),
      groups,
      group,
      groupIndex: Math.max(0, groups.findIndex((g) => g.id === group.id)),
      llmOnline: !!(app.globalData.meta && app.globalData.meta.llm_online)
    });
    return Promise.all([
      api.get('/api/groups/' + group.id + '/inventory', null, { silent: true }),
      api.get('/api/groups/' + group.id + '/plans', null, { silent: true }),
      api.get('/api/notifications', null, { silent: true }),
      api.get('/api/me/nutrition', { days: 1 }, { silent: true })
    ]).then(([inv, plans, notes, nut]) => {
      const day = nut.series[nut.series.length - 1] || {};
      const t = nut.target;
      const ratio = t.kcal ? Math.round((day.kcal || 0) / t.kcal * 100) : 0;
      const over = (day.kcal || 0) > t.kcal * 1.1;
      const today = {
        kcal: day.kcal || 0, target: t.kcal, pct: pct(day.kcal, t.kcal), over,
        left: Math.max(0, t.kcal - (day.kcal || 0)),
        ratio,
        meter: over ? ratio : Math.min(100, ratio),
        macros: [
          { name: '蛋白质', v: Math.round(day.protein || 0), t: t.protein_g, pct: pct(day.protein, t.protein_g), cls: '', color: 'green' },
          { name: '碳水', v: Math.round(day.carb || 0), t: t.carb_g, pct: pct(day.carb, t.carb_g), cls: 'blue', color: 'blue' },
          { name: '脂肪', v: Math.round(day.fat || 0), t: t.fat_g, pct: pct(day.fat, t.fat_g), cls: 'warn', color: 'orange' }
        ]
      };
      const plan = plans.find((p) => p.status === 'done') || plans[0] || null;
      const alerts = inv.alerts.slice(0, 8).map(decorateAlert);
      const patch = { alerts, latestPlan: plan, planMeta: planMeta(plan), unread: notes.unread, today, loading: false };
      const tip = chefTip(alerts, today, plan);
      if (tip !== this.data.tip) patch.tip = tip; // don't re-type the same line on every onShow
      this.setData(patch);
    }).catch(() => this.setData({ loading: false }));
  },

  onGroupChange(e) {
    const g = this.data.groups[e.detail.value];
    app.switchGroup(g.id);
    this.load();
  },

  go(e) {
    const url = e.currentTarget.dataset.url;
    const tabs = ['/pages/inventory/', '/pages/planner/', '/pages/budget/', '/pages/profile/'];
    if (tabs.some((t) => url.indexOf(t) === 0)) wx.switchTab({ url });
    else wx.navigateTo({ url });
  },

  recognize(e) {
    wx.navigateTo({ url: '/pages/recognize/recognize?kind=' + e.currentTarget.dataset.kind + '&camera=1' });
  },

  openPlan() {
    if (this.data.latestPlan) wx.navigateTo({ url: '/pages/plan/plan?id=' + this.data.latestPlan.id });
    else wx.switchTab({ url: '/pages/planner/planner' });
  },

  openShopping() {
    const p = this.data.latestPlan;
    if (p && p.status === 'done') wx.navigateTo({ url: '/pages/shopping/shopping?id=' + p.id });
    else wx.showToast({ title: '请先生成膳食计划', icon: 'none' });
  }
});
