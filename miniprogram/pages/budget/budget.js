const api = require('../../utils/api');
const { money, pct } = require('../../utils/util');
const app = getApp();

Page({
  data: {
    group: null,
    isAdmin: false,
    period: 'week',
    report: null,
    expenses: [],
    budgetMode: 'per_person',
    budgetAmount: '',
    showManual: false,
    manual: { total_amount: '', merchant: '', note: '' }
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) this.getTabBar().setData({ selected: 3 });
    app.ready().then(() => this.load());
    if (!this.off) this.off = app.onSocket((ev) => { if (ev.type === 'expense.added' || ev.type === 'group.updated') this.load(); });
  },
  onUnload() { if (this.off) this.off(); },
  onPullDownRefresh() { this.load().then(() => wx.stopPullDownRefresh()); },

  load() {
    const group = app.currentGroup();
    if (!group) return Promise.resolve();
    this.setData({ group, isAdmin: group.role === 'admin' });
    return Promise.all([
      api.get('/api/groups/' + group.id),
      api.get('/api/groups/' + group.id + '/expenses/report', { period: this.data.period }),
      api.get('/api/groups/' + group.id + '/expenses', { limit: 30 })
    ]).then(([g, report, expenses]) => {
      report.totalText = money(report.total);
      report.usePct = report.budget ? Math.min(100, pct(report.total / report.budget)) : 0;
      report.by_category.forEach((c) => { c.pctText = pct(c.share); });
      report.useText = report.budget ? pct(report.total / report.budget) : null;
      expenses.forEach((e) => {
        e.date = e.paid_at.slice(5, 10).replace('-', '/');
        e.itemText = e.items.map((i) => i.name).join('、');
        e.sourceText = e.source === 'manual' ? '手动' : e.source === 'label' ? '价签' : '小票';
      });
      this.setData({ report, expenses, budgetMode: g.budget_mode, budgetAmount: g.budget_amount ? String(g.budget_amount) : '' });
    });
  },

  setPeriod(e) { this.setData({ period: e.currentTarget.dataset.p }); this.load(); },

  photo() { wx.navigateTo({ url: '/pages/recognize/recognize?kind=receipt&camera=1' }); },

  setMode(e) { this.setData({ budgetMode: e.currentTarget.dataset.m }); },
  onAmount(e) { this.setData({ budgetAmount: e.detail.value }); },
  saveBudget() {
    api.put('/api/groups/' + this.data.group.id, { budget_mode: this.data.budgetMode, budget_amount: Number(this.data.budgetAmount || 0) })
      .then(() => { wx.showToast({ title: '预算已保存' }); app.refreshGroups(); this.load(); });
  },

  toggleManual() { this.setData({ showManual: !this.data.showManual }); },
  onManual(e) { this.setData({ ['manual.' + e.currentTarget.dataset.k]: e.detail.value }); },
  saveManual() {
    const m = this.data.manual;
    if (!Number(m.total_amount)) return wx.showToast({ title: '请输入实付金额', icon: 'none' });
    api.post('/api/groups/' + this.data.group.id + '/expenses', { total_amount: Number(m.total_amount), merchant: m.merchant, note: m.note })
      .then(() => { this.setData({ showManual: false, manual: { total_amount: '', merchant: '', note: '' } }); this.load(); });
  },

  expenseActions(e) {
    const ex = this.data.expenses[e.currentTarget.dataset.index];
    const list = ex.upload_id ? ['查看小票', '删除'] : ['删除'];
    wx.showActionSheet({
      itemList: list,
      success: (r) => {
        if (list[r.tapIndex] === '删除') api.del('/api/expenses/' + ex.id).then(() => this.load());
        if (list[r.tapIndex] === '查看小票') {
          const config = require('../../config');
          wx.downloadFile({
            url: config.baseUrl + '/api/uploads/' + ex.upload_id,
            header: { Authorization: 'Bearer ' + api.getToken() },
            success: (res) => wx.previewImage({ urls: [res.tempFilePath] })
          });
        }
      }
    });
  }
});
