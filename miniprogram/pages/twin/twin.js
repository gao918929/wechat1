const api = require('../../utils/api');
const { VARIANT } = require('../../utils/util');
const app = getApp();

function topScores(map, positive) {
  return Object.keys(map || {}).map((k) => ({ name: k, score: map[k] }))
    .filter((x) => (positive ? x.score > 0 : x.score < 0))
    .sort((a, b) => (positive ? b.score - a.score : a.score - b.score)).slice(0, 8);
}

Page({
  data: { view: 'me', twin: null, groupTwin: null, groupError: '', likes: '', dislikes: '', notes: '', vm: null },

  onShow() { app.ready().then(() => this.load()); },

  setView(e) { this.setData({ view: e.currentTarget.dataset.v }); this.load(); },

  load() {
    if (this.data.view === 'group') {
      const g = app.currentGroup();
      return api.get('/api/groups/' + g.id + '/twin', null, { silent: true })
        .then((t) => this.setData({ groupTwin: t, groupError: '', vm: this.viewModel(t.data) }))
        .catch((e) => this.setData({ groupTwin: null, groupError: e.message }));
    }
    return api.get('/api/me/twin').then((t) => {
      const manual = (t.data && t.data.manual) || {};
      this.setData({ twin: t, vm: this.viewModel(t.data), likes: (manual.likes || []).join('、'),
        dislikes: (manual.dislikes || []).join('、'), notes: manual.notes || '' });
    });
  },

  viewModel(d) {
    d = d || {};
    const choices = d.variant_choices || {};
    return {
      favor: topScores(d.dish_scores, true), avoid: topScores(d.dish_scores, false),
      ingredients: topScores(d.ingredient_scores, true).concat(topScores(d.ingredient_scores, false)),
      subs: d.substitutions || [], recent: (d.recent_dishes || []).slice(0, 10).join('、'),
      calibration: Object.keys(d.calibration || {}).map((k) => ({ name: k, factor: d.calibration[k].factor, n: d.calibration[k].n })),
      choices: Object.keys(choices).map((k) => ({ name: VARIANT[k] || k, n: choices[k] })),
      price: d.price_sensitivity ? { high: '价格敏感（常买低于参考价）', mid: '价格适中', low: '偏好品质（常买高于参考价）' }[d.price_sensitivity] : '',
      feedback: d.feedback_count || 0,
      members: d.members || [], unionAvoid: (d.union_avoid || []).join('、'), unionAllergens: (d.union_allergens || []).join('、'),
      budget: d.budget_habits || null
    };
  },

  onInput(e) { this.setData({ [e.currentTarget.dataset.k]: e.detail.value }); },

  save() {
    const split = (s) => s.split(/[、,，\s]+/).filter(Boolean);
    api.put('/api/me/twin', { likes: split(this.data.likes), dislikes: split(this.data.dislikes), notes: this.data.notes })
      .then(() => { wx.showToast({ title: '已更新' }); this.load(); });
  },

  refresh() {
    api.post('/api/me/twin/refresh', {}).then(() => { wx.showToast({ title: '已按最新反馈更新' }); this.load(); });
  }
});
