const api = require('../../utils/api');
const config = require('../../config');
const { chooseImage, MEAL } = require('../../utils/util');
const app = getApp();

const TITLES = { ingredients: '食材识别', receipt: '小票 / 价签记账', meal: '餐后拍照复盘' };

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
    this.setData({ rec, card: rec.card, items: rec.card.items || [], include, reply: rec.card.message || '' });
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
    this.setData({ ['include.' + id]: !this.data.include[id] });
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
      this.setData({ done: r, doneText: { added: j(r.added), skipped: j(r.skipped), deviation: j(r.deviation) } });
      let msg = '已确认';
      if (r.kind === 'ingredients') msg = '已入库 ' + r.added.length + ' 种';
      if (r.kind === 'receipt') msg = '已记账 ¥' + r.total;
      if (r.kind === 'meal') msg = r.context === 'home' ? '已记录并扣减库存' : '外食：仅记录营养';
      wx.showToast({ title: msg, icon: 'success' });
    });
  }
});
