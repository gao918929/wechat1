const api = require('../../utils/api');
const { LEVEL_TAG } = require('../../utils/util');
const app = getApp();

Page({
  data: {
    group: null,
    isAdmin: false,
    items: [],
    alerts: [],
    chatText: '',
    chatReply: '',
    showAdd: false,
    form: { name: '', quantity: '', weight_g: '', purchase_date: '' },
    suggestions: [],
    levelTag: LEVEL_TAG
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) this.getTabBar().setData({ selected: 1 });
    app.ready().then(() => this.load());
    if (!this.off) {
      this.off = app.onSocket((ev) => {
        if (ev.type === 'inventory.updated') {
          this.load();
          if (ev.by && ev.by !== (app.globalData.user || {}).nickname) wx.showToast({ title: ev.by + ' 更新了库存', icon: 'none' });
        }
      });
    }
  },

  onUnload() { if (this.off) this.off(); },
  onPullDownRefresh() { this.load().then(() => wx.stopPullDownRefresh()); },

  load() {
    const group = app.currentGroup();
    if (!group) return Promise.resolve();
    this.setData({ group, isAdmin: group.role === 'admin' });
    return api.get('/api/groups/' + group.id + '/inventory').then((d) => this.setData({ items: d.items, alerts: d.alerts }));
  },

  photo() { wx.navigateTo({ url: '/pages/recognize/recognize?kind=ingredients&camera=1' }); },
  receipt() { wx.navigateTo({ url: '/pages/recognize/recognize?kind=receipt&camera=1' }); },

  onChatInput(e) { this.setData({ chatText: e.detail.value }); },

  sendChat() {
    const text = this.data.chatText.trim();
    if (!text) return;
    api.post('/api/groups/' + this.data.group.id + '/inventory/chat', { text }).then((r) => {
      this.setData({ chatText: '', chatReply: r.ok ? '✅ ' + r.applied.join('；') : r.message });
      this.load();
    });
  },

  toggleAdd() { this.setData({ showAdd: !this.data.showAdd }); },

  onForm(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ ['form.' + key]: e.detail.value });
    if (key === 'name' && e.detail.value) {
      api.get('/api/wiki/ingredients', { q: e.detail.value, limit: 6 }, { silent: true })
        .then((list) => this.setData({ suggestions: list.map((i) => i.name) }));
    }
  },

  pickSuggestion(e) { this.setData({ 'form.name': e.currentTarget.dataset.name, suggestions: [] }); },

  submitAdd() {
    const f = this.data.form;
    if (!f.name) return wx.showToast({ title: '请输入食材名', icon: 'none' });
    const item = { name: f.name, source: 'manual' };
    if (f.quantity) item.quantity = Number(f.quantity);
    if (f.weight_g) item.weight_g = Number(f.weight_g);
    if (f.purchase_date) item.purchase_date = f.purchase_date;
    api.post('/api/groups/' + this.data.group.id + '/inventory', { items: [item] }).then(() => {
      this.setData({ showAdd: false, form: { name: '', quantity: '', weight_g: '', purchase_date: '' } });
      this.load();
    });
  },

  itemActions(e) {
    const item = this.data.items[e.currentTarget.dataset.index];
    const actions = ['用掉一部分', '全部用完'];
    if (this.data.isAdmin) actions.push('修改重量', '标记为不新鲜', '删除');
    wx.showActionSheet({
      itemList: actions,
      success: (res) => {
        const a = actions[res.tapIndex];
        if (a === '全部用完') this.consume(item, null);
        else if (a === '用掉一部分') this.ask('用掉多少克？', (v) => this.consume(item, Number(v)));
        else if (a === '修改重量') this.ask('实际重量（克）', (v) => api.put('/api/inventory/' + item.id, { weight_g: Number(v) }).then(() => this.load()));
        else if (a === '标记为不新鲜') api.put('/api/inventory/' + item.id, { freshness: 'not_fresh' }).then(() => this.load());
        else if (a === '删除') api.del('/api/inventory/' + item.id).then(() => this.load());
      }
    });
  },

  ask(title, cb) {
    wx.showModal({
      title, editable: true, placeholderText: '输入数字',
      success: (r) => { if (r.confirm && r.content && !isNaN(Number(r.content))) cb(r.content); }
    });
  },

  consume(item, grams) {
    const body = grams ? { weight_g: grams } : {};
    api.post('/api/inventory/' + item.id + '/consume', body).then(() => this.load());
  }
});
