const api = require('../../utils/api');
const config = require('../../config');
// ingredient → /assets/px/<icon>.svg (iconFor) or category-coloured initial tile (initialOf): utils/util.js
const { chooseImage, MEAL, iconFor, initialOf } = require('../../utils/util');
const app = getApp();

const TITLES = { ingredients: '食材识别', receipt: '小票 / 价签记账', meal: '餐后拍照复盘' };

// ---- pixel display helpers (presentation only)
// Adds display-only fields to a card item; the original fields are untouched.
function decorate(i, kind) {
  const q = Number(i.quantity);
  const raw = i.weight_text || (i.needs_weight ? '已识别食材，需补充重量' : '');
  return Object.assign({}, i, {
    // dishes without a matching ingredient icon get the rice-bowl icon
    icon: iconFor(i.canonical || i.name) || (kind === 'meal' ? 'meal' : ''),
    initial: initialOf(i.name),
    // not matched to a known ingredient (待确认 / non-food receipt line) → neutral grey tile
    cat: kind !== 'meal' && !i.canonical ? 'other' : (i.category || 'vegetables'),
    qtyText: q >= 1 && Math.floor(q) === q ? q + ' 个' : '',   // never "0.34 个"
    weightShort: i.needs_weight ? '需补充重量' : raw.replace(/（估算）|\(估算\)/g, '').trim(),
    isEst: !!i.is_estimated && !i.needs_weight && !!raw,
    method: (i.estimate && i.estimate.method) || '',
    renamed: !!i.recognized_as && i.recognized_as !== i.name,
    pending: i.status === 'confirm',
    notFresh: i.freshness === 'not_fresh'
  });
}
function countPicked(items, include) {
  return items.filter((i) => include[i.id]).length;
}

Page({
  data: {
    kind: 'ingredients',
    title: '',
    rec: null,
    items: [],
    card: {},
    loading: false,
    chatText: '',
    reply: '',
    editIndex: -1,
    edit: {},
    include: {},
    myShare: 1,
    meals: ['breakfast', 'lunch', 'dinner'],
    mealLabels: ['早餐', '午餐', '晚餐'],
    mealIndex: 2,
    addToInventory: true,
    planId: null,
    planDay: null,
    done: null,
    doneText: {},
    doneItems: [],
    doneNutri: {},
    pickCount: 0,
    MEAL
  },

  onLoad(q) {
    const kind = q.kind || 'ingredients';
    const hour = new Date().getHours();
    this.setData({
      kind, title: TITLES[kind], planId: q.plan_id ? Number(q.plan_id) : null, planDay: q.day ? Number(q.day) : null,
      mealIndex: q.meal ? Math.max(0, this.data.meals.indexOf(q.meal)) : (hour < 10 ? 0 : hour < 15 ? 1 : 2)
    });
    app.ready().then(() => (q.camera ? this.takePhoto() : this.manual()));
  },

  takePhoto() {
    chooseImage().then((path) => {
      this.setData({ loading: true, reply: '' });
      wx.showLoading({ title: 'AI 识别中…' });
      const end = () => { wx.hideLoading(); this.setData({ loading: false }); };
      return api.upload('/api/recognitions', path, { kind: this.data.kind, group_id: String(app.globalData.groupId) })
        .then((rec) => { end(); this.setRec(rec); }, (err) => { end(); throw err; });
    }).catch(() => { if (!this.data.rec) this.manual(); });
  },

  // An empty card (no photo) filled in by chat or tap-to-edit. The endpoint takes form fields.
  manual() {
    return this.manualForm().then((rec) => rec && this.setRec(rec));
  },

  manualForm() {
    return new Promise((resolve) => {
      wx.request({
        url: config.baseUrl + '/api/recognitions/manual',
        method: 'POST',
        header: { 'content-type': 'application/x-www-form-urlencoded', Authorization: 'Bearer ' + api.getToken() },
        data: { kind: this.data.kind, group_id: app.globalData.groupId },
        success: (r) => resolve(r.statusCode < 400 ? r.data : null),
        fail: () => resolve(null)
      });
    });
  },

  setRec(rec) {
    const include = {};
    (rec.card.items || []).forEach((i) => { include[i.id] = i.status !== 'confirm'; });
    const items = (rec.card.items || []).map((i) => decorate(i, this.data.kind));
    this.setData({ rec, card: rec.card, items, include, pickCount: countPicked(items, include), reply: rec.card.message || '' });
  },

  onChat(e) { this.setData({ chatText: e.detail.value }); },

  sendChat() {
    const text = this.data.chatText.trim();
    if (!text || !this.data.rec) return;
    api.post('/api/recognitions/' + this.data.rec.id + '/chat', { text }).then((r) => {
      this.setRec(r);
      this.setData({ chatText: '', reply: r.message });
    });
  },

  // ---- tap-to-edit
  openEdit(e) {
    const i = Number(e.currentTarget.dataset.index);
    const it = this.data.items[i];
    this.setData({ editIndex: i, edit: { name: it.name, weight_g: it.weight_g || '', quantity: it.quantity || '', amount: it.amount || '', unit_price: it.unit_price || '' } });
  },
  closeEdit() { this.setData({ editIndex: -1 }); },
  onEdit(e) { this.setData({ ['edit.' + e.currentTarget.dataset.key]: e.detail.value }); },

  saveEdit() {
    const it = this.data.items[this.data.editIndex];
    const ed = this.data.edit;
    const ops = [];
    if (ed.name && ed.name !== it.name) ops.push({ op: 'rename', from: it.name, to: ed.name });
    const name = ed.name || it.name;
    const set = { op: 'set', name };
    if (ed.weight_g !== '' && Number(ed.weight_g) !== it.weight_g) set.weight_g = Number(ed.weight_g);
    if (ed.quantity !== '' && Number(ed.quantity) !== it.quantity) set.quantity = Number(ed.quantity);
    if (ed.amount !== '' && Number(ed.amount) !== it.amount) set.amount = Number(ed.amount);
    if (ed.unit_price !== '' && Number(ed.unit_price) !== it.unit_price) set.unit_price = Number(ed.unit_price);
    ops.push(set);
    this.patch({ ops }).then(() => this.closeEdit());
  },

  removeItem() {
    const it = this.data.items[this.data.editIndex];
    this.patch({ ops: [{ op: 'remove', name: it.name }] }).then(() => this.closeEdit());
  },

  patch(body) {
    return api.put('/api/recognitions/' + this.data.rec.id, body).then((r) => this.setRec(r));
  },

  toggleInclude(e) {
    const id = e.currentTarget.dataset.id;
    const on = !this.data.include[id];
    const include = Object.assign({}, this.data.include, { [id]: on });
    this.setData({ ['include.' + id]: on, pickCount: countPicked(this.data.items, include) });
  },

  setContext(e) { this.patch({ context: e.currentTarget.dataset.v }); },
  onMeta(e) {
    const key = e.currentTarget.dataset.key;
    const v = key === 'total' ? Number(e.detail.value) : e.detail.value;
    this.patch({ [key]: v });
  },
  onShare(e) { this.setData({ myShare: Number(e.detail.value) }); },
  onMeal(e) { this.setData({ mealIndex: Number(e.detail.value) }); },
  onAddInv(e) { this.setData({ addToInventory: e.detail.value }); },

  confirm() {
    const ids = this.data.items.filter((i) => this.data.include[i.id]).map((i) => i.id);
    if (this.data.kind !== 'receipt' && !ids.length) return wx.showToast({ title: '没有要确认的条目', icon: 'none' });
    const body = { item_ids: ids, add_to_inventory: this.data.addToInventory, my_share: this.data.myShare,
      meal: this.data.meals[this.data.mealIndex] };
    if (this.data.planId) { body.plan_id = this.data.planId; body.plan_day = this.data.planDay; }
    api.post('/api/recognitions/' + this.data.rec.id + '/confirm', body).then((r) => {
      const j = (a) => (a || []).join('、');
      // display only: the "获得物品!" slots (stored items, or the dishes just logged) and rounded nutrition
      const got = r.added || r.added_to_inventory
        || (r.kind === 'meal' ? this.data.items.filter((i) => this.data.include[i.id]).map((i) => i.name) : []);
      const n = r.nutrition || {};
      const num = (v, d) => (typeof v === 'number' ? String(Math.round(v * d) / d) : '–');
      this.setData({ done: r, doneText: { added: j(r.added), skipped: j(r.skipped), deviation: j(r.deviation), toInventory: j(r.added_to_inventory) },
        doneNutri: { kcal: num(n.kcal, 1), protein: num(n.protein, 10) },
        doneItems: got.map((name, key) => {
          const src = this.data.items.find((i) => i.name === name) || {};
          return { key, name, icon: src.icon || iconFor(name), initial: src.initial || initialOf(name), cat: src.cat || 'vegetables' };
        }) });
      let msg = '已确认';
      if (r.kind === 'ingredients') msg = '已入库 ' + r.added.length + ' 种';
      if (r.kind === 'receipt') msg = '已记账 ¥' + r.total;
      if (r.kind === 'meal') msg = r.context === 'home' ? '已记录并扣减库存' : '外食：仅记录营养';
      wx.showToast({ title: msg, icon: 'success' });
    });
  }
});
