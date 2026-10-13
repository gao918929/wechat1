const api = require('../../utils/api');
const app = getApp();

const SEX = [{ key: '', label: '未填' }, { key: 'male', label: '男' }, { key: 'female', label: '女' }];

function toggle(list, key) {
  const i = list.indexOf(key);
  if (i >= 0) list.splice(i, 1); else list.push(key);
  return list;
}

Page({
  data: {
    meta: null,
    form: {},
    sexes: SEX,
    sexIndex: 0,
    activityIndex: 1,
    targets: null,
    customAvoid: '',
    customAllergen: '',
    likesText: '',
    sel: { groups: {}, allergens: {}, avoidances: {} },
    extraAvoid: [],
    extraAllergens: []
  },

  onShow() {
    app.ready().then(() => (app.globalData.meta ? app.globalData.meta : app.loadMeta())).then((meta) => {
      this.setData({ meta });
      return api.get('/api/me');
    }).then((d) => this.fill(d.user)).then(() => this.loadTargets());
  },

  fill(u) {
    const meta = this.data.meta;
    const knownAvoid = meta.avoid_options.map((o) => o.key);
    const knownAllergen = meta.allergen_options.map((o) => o.key);
    const asMap = (arr) => (arr || []).reduce((m, k) => { m[k] = true; return m; }, {});
    this.setData({
      form: {
        nickname: u.nickname, age: u.age || '', height_cm: u.height_cm || '', weight_kg: u.weight_kg || '',
        body_fat_pct: u.body_fat_pct || '', goal: u.goal, max_spicy: u.max_spicy
      },
      sexIndex: Math.max(0, SEX.findIndex((s) => s.key === (u.sex || ''))),
      activityIndex: Math.max(0, meta.activity_levels.findIndex((a) => a.key === u.activity_level)),
      sel: { groups: asMap(u.dietary_groups), allergens: asMap(u.allergens), avoidances: asMap(u.avoidances) },
      extraAvoid: (u.avoidances || []).filter((a) => knownAvoid.indexOf(a) < 0),
      extraAllergens: (u.allergens || []).filter((a) => knownAllergen.indexOf(a) < 0),
      likesText: (u.likes || []).join('、')
    });
  },

  loadTargets() {
    return api.get('/api/me/targets', null, { silent: true }).then((t) => this.setData({ targets: t }));
  },

  onField(e) { this.setData({ ['form.' + e.currentTarget.dataset.k]: e.detail.value }); },
  onSex(e) { this.setData({ sexIndex: Number(e.detail.value) }); },
  onActivity(e) { this.setData({ activityIndex: Number(e.detail.value) }); },
  setGoal(e) { this.setData({ 'form.goal': e.currentTarget.dataset.k }); },
  onSpicy(e) { this.setData({ 'form.max_spicy': e.detail.value }); },
  toggleSel(e) {
    const { group, k } = e.currentTarget.dataset;
    this.setData({ ['sel.' + group + '.' + k]: !this.data.sel[group][k] });
  },
  onCustom(e) { this.setData({ [e.currentTarget.dataset.k]: e.detail.value }); },
  addCustom(e) {
    const which = e.currentTarget.dataset.k;
    const field = which === 'avoid' ? 'customAvoid' : 'customAllergen';
    const list = which === 'avoid' ? 'extraAvoid' : 'extraAllergens';
    const v = this.data[field].trim();
    if (!v) return;
    this.setData({ [list]: toggle(this.data[list].slice(), v), [field]: '' });
  },
  removeExtra(e) {
    const { list, v } = e.currentTarget.dataset;
    this.setData({ [list]: this.data[list].filter((x) => x !== v) });
  },
  onLikes(e) { this.setData({ likesText: e.detail.value }); },

  save() {
    const f = this.data.form;
    const keys = (m) => Object.keys(m).filter((k) => m[k]);
    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    const body = {
      nickname: f.nickname, sex: SEX[this.data.sexIndex].key, age: num(f.age), height_cm: num(f.height_cm),
      weight_kg: num(f.weight_kg), body_fat_pct: num(f.body_fat_pct),
      activity_level: this.data.meta.activity_levels[this.data.activityIndex].key, goal: f.goal,
      max_spicy: Number(f.max_spicy), dietary_groups: keys(this.data.sel.groups),
      allergens: keys(this.data.sel.allergens).concat(this.data.extraAllergens),
      avoidances: keys(this.data.sel.avoidances).concat(this.data.extraAvoid),
      likes: this.data.likesText.split(/[、,，\s]+/).filter(Boolean)
    };
    Object.keys(body).forEach((k) => { if (body[k] === null) delete body[k]; });
    api.put('/api/me', body).then((r) => {
      app.globalData.user = r.user;
      wx.showToast({ title: '已保存' });
      this.loadTargets();
    });
  },

  go(e) { wx.navigateTo({ url: e.currentTarget.dataset.url }); }
});
