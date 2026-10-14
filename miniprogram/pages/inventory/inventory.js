const api = require('../../utils/api');
const { LEVEL_TAG } = require('../../utils/util');
const app = getApp();

// Pixel ingredient icons (/assets/px/<icon>.svg). First matching keyword wins; no match → category initial tile.
const ICON_RULES = [
  ['egg', ['蛋']],
  ['tomato', ['番茄', '西红柿', '圣女果']],
  ['carrot', ['胡萝卜', '红萝卜']],
  ['broccoli', ['西兰花', '西蓝花', '花椰菜', '花菜']],
  ['milk', ['牛奶', '酸奶', '奶粉']],
  ['fish', ['鱼']],
  ['chili', ['辣椒']],
  ['meat', ['肉', '排骨', '鸡腿', '鸡翅', '牛排', '五花', '里脊']]
];
// The keyword that appears earliest in the name wins ("番茄炒蛋" → tomato, "鸡蛋" → egg).
function iconFor(name) {
  const n = name || '';
  let best = ''; let at = Infinity;
  ICON_RULES.forEach((r) => r[1].forEach((k) => {
    const p = n.indexOf(k);
    if (p >= 0 && p < at) { at = p; best = r[0]; }
  }));
  return best;
}
// Initial for the fallback tile; skip a size prefix so 大白菜 / 大米 do not both read "大".
function initialOf(name) {
  const n = name || '?';
  return n.length > 1 && /^[大小]/.test(n) ? n.charAt(1) : n.charAt(0);
}
// Freshness meter tone by level (8-cell HP bar).
const METER_TONE = { ok: 'green', near_expiry: 'orange', expired: 'red', not_fresh: 'red' };

// Visual freshness: a bar that drains as the item approaches expiry.
function decorate(it) {
  const f = it.freshness;
  const pct = f.level === 'expired' || f.level === 'not_fresh' ? 100
    : Math.max(6, Math.min(100, Math.round((f.days_left / Math.max(1, f.shelf_days)) * 100)));
  const daysText = f.level === 'expired' ? '已过期' : f.level === 'not_fresh' ? '不新鲜'
    : f.days_left === 0 ? '今天到期' : f.days_left + ' 天';
  // Count only when it is a whole number of pieces ≥ 1 — never show "0.34 个".
  const q = Number(it.quantity);
  const qtyText = q >= 1 && Math.floor(q) === q ? q + ' 个' : '';
  let weightText = (it.weight_text || '').replace(/（估算）|\(估算\)/g, '').trim();
  if (!weightText && it.grams) weightText = '约 ' + Math.round(it.grams) + ' g';
  const amount = [qtyText, weightText].filter(Boolean).join(' · ');
  const urgent = f.level !== 'ok' || f.days_left === 0;
  return Object.assign(it, {
    initial: initialOf(it.name), cat: it.category || 'vegetables', pct, daysText,
    barCls: f.level === 'ok' ? '' : f.level === 'near_expiry' ? 'warn' : 'danger',
    amount: amount || (it.needs_weight ? '需补充重量' : ''),
    // pixel display fields
    icon: iconFor(it.canonical || it.name),
    isEst: !!it.is_estimated && !!weightText,
    urgent,
    meterVal: f.level === 'expired' || f.level === 'not_fresh' ? 13 : Math.max(13, pct),
    meterTone: f.days_left === 0 && f.level === 'ok' ? 'orange' : (METER_TONE[f.level] || 'green'),
    expShort: (f.expires_on || '').slice(5),
    // "10 天" → pixel digits + unit; worded states (已过期 / 不新鲜 / 今天到期) stay as text
    daysNum: (f.level === 'ok' || f.level === 'near_expiry') && f.days_left > 0 ? String(f.days_left) : '',
    daysTone: f.level === 'ok' && f.days_left > 0 ? 'ok' : f.level === 'near_expiry' || f.level === 'ok' ? 'warn' : 'danger'
  });
}

Page({
  data: {
    group: null,
    isAdmin: false,
    items: [],
    alerts: [],
    chatText: '',
    chatReply: '',
    chatOk: true,
    alertNames: '',
    showAdd: false,
    stats: { total: 0, urgent: 0, needsWeight: 0 },
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
    return api.get('/api/groups/' + group.id + '/inventory').then((d) => {
      const items = d.items.map(decorate);
      this.setData({
        items, alerts: d.alerts,
        alertNames: (d.alerts || []).map((a) => a.name).join(' · '),
        stats: { total: items.length, urgent: d.alerts.length, needsWeight: d.needs_weight.length }
      });
    });
  },

  photo() { wx.navigateTo({ url: '/pages/recognize/recognize?kind=ingredients&camera=1' }); },
  receipt() { wx.navigateTo({ url: '/pages/recognize/recognize?kind=receipt&camera=1' }); },

  onChatInput(e) { this.setData({ chatText: e.detail.value }); },

  sendChat() {
    const text = this.data.chatText.trim();
    if (!text) return;
    api.post('/api/groups/' + this.data.group.id + '/inventory/chat', { text }).then((r) => {
      this.setData({ chatText: '', chatOk: !!r.ok, chatReply: r.ok ? (r.applied.join('；') || '收到，没有需要改动的食材') : r.message });
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
