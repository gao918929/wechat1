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
    loading: true
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
      const today = {
        kcal: day.kcal || 0, target: t.kcal, pct: pct(day.kcal, t.kcal), over: (day.kcal || 0) > t.kcal * 1.1,
        left: Math.max(0, t.kcal - (day.kcal || 0)),
        macros: [
          { name: '蛋白质', v: Math.round(day.protein || 0), t: t.protein_g, pct: pct(day.protein, t.protein_g), cls: '' },
          { name: '碳水', v: Math.round(day.carb || 0), t: t.carb_g, pct: pct(day.carb, t.carb_g), cls: 'blue' },
          { name: '脂肪', v: Math.round(day.fat || 0), t: t.fat_g, pct: pct(day.fat, t.fat_g), cls: 'warn' }
        ]
      };
      const plan = plans.find((p) => p.status === 'done') || plans[0] || null;
      this.setData({ alerts: inv.alerts.slice(0, 8), latestPlan: plan, unread: notes.unread, today, loading: false });
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
