const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    user: null,
    groups: [],
    groupIndex: 0,
    group: null,
    alerts: [],
    latestPlan: null,
    unread: 0,
    llmOnline: false,
    loading: true
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) this.getTabBar().setData({ selected: 0 });
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
    if (!group) return Promise.resolve();
    this.setData({
      user: app.globalData.user,
      groups,
      group,
      groupIndex: Math.max(0, groups.findIndex((g) => g.id === group.id)),
      llmOnline: !!(app.globalData.meta && app.globalData.meta.llm_online)
    });
    return Promise.all([
      api.get('/api/groups/' + group.id + '/inventory', null, { silent: true }),
      api.get('/api/groups/' + group.id + '/plans', null, { silent: true }),
      api.get('/api/notifications', null, { silent: true })
    ]).then(([inv, plans, notes]) => {
      this.setData({
        alerts: inv.alerts.slice(0, 6),
        latestPlan: plans.find((p) => p.status === 'done') || plans[0] || null,
        unread: notes.unread,
        loading: false
      });
    }).catch(() => this.setData({ loading: false }));
  },

  onGroupChange(e) {
    const g = this.data.groups[e.detail.value];
    app.switchGroup(g.id);
    this.load();
  },

  go(e) {
    const url = e.currentTarget.dataset.url;
    if (url.indexOf('/pages/inventory/') === 0 || url.indexOf('/pages/planner/') === 0 || url.indexOf('/pages/budget/') === 0) {
      wx.switchTab({ url });
    } else {
      wx.navigateTo({ url });
    }
  },

  recognize(e) {
    const kind = e.currentTarget.dataset.kind;
    wx.navigateTo({ url: '/pages/recognize/recognize?kind=' + kind + '&camera=1' });
  },

  openPlan() {
    if (this.data.latestPlan) wx.navigateTo({ url: '/pages/plan/plan?id=' + this.data.latestPlan.id });
  },

  openShopping() {
    const p = this.data.latestPlan;
    if (p && p.status === 'done') wx.navigateTo({ url: '/pages/shopping/shopping?id=' + p.id });
    else wx.showToast({ title: '请先生成膳食计划', icon: 'none' });
  }
});
