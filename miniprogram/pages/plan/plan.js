const api = require('../../utils/api');
const { MEAL, KIND, VARIANT, AGENT_ICON, money } = require('../../utils/util');
const app = getApp();

const LAYER = { hard: '禁忌', inventory: '库存', nutrition: '营养', budget: '预算' };

function decorateDay(day) {
  return Object.assign({}, day, {
    meals: day.meals.map((m) => Object.assign({}, m, {
      label: MEAL[m.meal] || m.meal,
      dishes: m.dishes.map((x) => Object.assign({}, x, {
        kindLabel: KIND[x.kind] || x.kind,
        kcal: Math.round(x.nutrition_per_serving.kcal),
        protein: Math.round(x.nutrition_per_serving.protein),
        costText: money(x.cost),
        invText: (x.uses_inventory || []).join('、'),
        notesText: (x.notes || []).join('；')
      }))
    }))
  });
}

Page({
  data: {
    id: null,
    status: 'pending',
    log: [],
    agents: [],
    intent: null,
    framework: null,
    streamDays: [],
    result: null,
    variants: [],
    active: '',
    variant: null,
    days: [],
    chosen: '',
    expanded: {},
    showDetails: false,
    rating: 0,
    error: ''
  },

  onLoad(q) {
    this.setData({ id: Number(q.id) });
    app.ready().then(() => this.start());
    this.off = app.onSocket((ev) => {
      if (ev.type === 'plan.edited' && ev.plan_id === this.data.id) this.loadPlan();
    });
  },

  onUnload() {
    if (this.stream) this.stream.stop();
    if (this.off) this.off();
  },

  start() {
    this.setData({ log: [], agents: [], streamDays: [] });
    this.agentMap = {};
    this.stream = api.streamPlan(this.data.id, 0, (ev) => this.onEvent(ev), (end) => {
      if (end.type === 'done' || end.type === 'error' || end.type === 'failed') this.loadPlan();
    });
  },

  addLog(text) {
    const log = this.data.log.concat([text]);
    this.setData({ log: log.slice(-40) });
  },

  onEvent(ev) {
    const d = ev.data || {};
    if (ev.type === 'intent') {
      const budget = d.budget && d.budget.total ? '预算 ¥' + d.budget.total : '未设预算';
      this.setData({ intent: d, status: 'running' });
      this.addLog('🧭 调度器解析指令：' + d.diners.length + ' 人 · ' + d.days + ' 天 · ' + budget + ' · ' +
        (d.differentiated ? '差异化多菜' : '全员兼容') + (d.hard_constraints.length ? ' · 硬约束：' + d.hard_constraints.join('、') : '') +
        '（' + (d.mode === 'llm' ? 'DeepSeek' : '离线规则引擎') + '）');
    } else if (ev.type === 'agent') {
      this.agentMap[d.agent] = d;
      const agents = Object.keys(this.agentMap).map((k) => Object.assign({ icon: AGENT_ICON[k] }, this.agentMap[k]));
      this.setData({ agents });
      this.addLog((AGENT_ICON[d.agent] || '•') + ' ' + d.title + ' 完成（' + (d.mode === 'llm' ? '独立 LLM 调用' : '规则') + '，' + d.seconds + 's）');
    } else if (ev.type === 'framework') {
      this.setData({ framework: d });
      this.addLog('📐 总体框架已确定，开始编排菜单');
    } else if (ev.type === 'validation') {
      const layers = Object.keys(d.layers).map((k) => LAYER[k] + (d.layers[k].passed ? '✓' : '✗')).join(' ');
      this.addLog('🔎 三层校验［' + VARIANT[d.variant] + '］第 ' + (d.attempt + 1) + ' 轮：' + layers);
    } else if (ev.type === 'revision') {
      d.rounds.forEach((r) => this.addLog('↩️ 退回' + r.title + '修订：' + (r.applied.length ? r.applied.slice(0, 3).join('；') : '无可行修改')));
    } else if (ev.type === 'conflict') {
      this.addLog('⚖️ 检测到取舍：' + d.conflicts.join('；') + ' → 生成多套方案');
    } else if (ev.type === 'cached') {
      this.addLog('⚡ ' + d.message);
    } else if (ev.type === 'variant') {
      this.addLog('📋 ' + d.title + '：¥' + money(d.summary.total_cost) + (d.passed ? ' ✓' : ' （部分约束未满足）'));
    } else if (ev.type === 'day') {
      this.setData({ streamDays: this.data.streamDays.concat([decorateDay(d.day)]) });
    } else if (ev.type === 'shopping') {
      this.addLog('🛒 购物清单已生成：¥' + money(d.shopping.total_cost) + '（人均 ¥' + money(d.shopping.per_person_cost) + '）');
    } else if (ev.type === 'done') {
      this.addLog('✅ 完成');
    } else if (ev.type === 'error') {
      this.setData({ error: d.message, status: 'failed' });
    }
  },

  loadPlan() {
    return api.get('/api/plans/' + this.data.id).then((p) => {
      if (p.status !== 'done') {
        this.setData({ status: p.status, error: p.error });
        return;
      }
      const result = p.result;
      const active = this.data.active || p.chosen_variant || result.recommended;
      this.setData({ status: 'done', result, chosen: p.chosen_variant, conflictsText: (result.conflicts || []).join('；'), variants: result.variants.map((v) => ({ key: v.key, title: v.title })) });
      this.selectVariant(active);
    });
  },

  selectVariant(key) {
    const v = this.data.result.variants.find((x) => x.key === key) || this.data.result.variants[0];
    const s = v.summary;
    const vm = Object.assign({}, v, {
      costText: money(s.total_cost), perPersonText: money(s.per_person_cost),
      usePct: s.budget_utilization ? Math.min(100, Math.round(s.budget_utilization * 100)) : 0,
      nearUsed: s.near_expiry_used.map((u) => u.name + '（第' + u.day + '天）').join('、'),
      nearUnused: s.near_expiry_unused.map((u) => u.name).join('、'),
      issues: v.validation.issues.slice(0, 8).map((i) => i.message),
      satisfiedText: v.validation.suggestions ? v.validation.suggestions.satisfied.join('、') : ''
    });
    this.setData({ active: v.key, variant: vm, days: v.days.map(decorateDay) });
  },

  onTab(e) { this.selectVariant(e.currentTarget.dataset.key); },

  choose() {
    api.post('/api/plans/' + this.data.id + '/choose', { variant: this.data.active }).then(() => {
      this.setData({ chosen: this.data.active });
      wx.showToast({ title: '已选用，偏好已记入数字孪生', icon: 'none' });
    });
  },

  toggleDish(e) {
    const k = e.currentTarget.dataset.k;
    this.setData({ ['expanded.' + k]: !this.data.expanded[k] });
  },

  toggleDetails() { this.setData({ showDetails: !this.data.showDetails }); },

  feedback(body) {
    return api.post('/api/plans/' + this.data.id + '/feedback', Object.assign({ variant: this.data.active }, body)).then((r) => {
      if (r.message) wx.showToast({ title: r.message, icon: 'none' });
      if (r.variant) return this.loadPlan();
      return r;
    });
  },

  dishActions(e) {
    const { day, meal, name, kind } = e.currentTarget.dataset;
    wx.showActionSheet({
      itemList: ['❤ 收藏这道菜', '🔄 换一道', '🗑 删除这道菜'],
      success: (res) => {
        if (res.tapIndex === 0) this.feedback({ kind: 'favorite', dish: name });
        if (res.tapIndex === 2) this.feedback({ kind: 'delete_dish', day, meal, dish: name });
        if (res.tapIndex === 1) this.pickReplacement(day, meal, name, kind);
      }
    });
  },

  pickReplacement(day, meal, name, kind) {
    api.get('/api/wiki/dishes', { kind }).then((list) => {
      const forbidden = this.data.result.hard_constraint_labels || [];
      const options = list.filter((d) => d.name !== name && d.meals.indexOf(meal) >= 0)
        .filter((d) => !d.ingredients.some((i) => forbidden.indexOf(i.name) >= 0)).slice(0, 6);
      if (!options.length) return wx.showToast({ title: '没有可替换的同类菜', icon: 'none' });
      wx.showActionSheet({
        itemList: options.map((d) => d.name),
        success: (res) => this.feedback({ kind: 'replace_dish', day, meal, dish: name, with_dish: options[res.tapIndex].name })
      });
    });
  },

  eat(e) {
    const { day, meal } = e.currentTarget.dataset;
    wx.showActionSheet({
      itemList: ['按计划吃了（扣减库存）', '拍照复盘这一餐'],
      success: (res) => {
        if (res.tapIndex === 0) {
          api.post('/api/plans/' + this.data.id + '/eat', { variant: this.data.active, day, meal }).then((r) => {
            wx.showToast({ title: r.already_deducted ? '已记录（库存此前已扣减）' : '已记录并扣减库存', icon: 'none' });
          });
        } else {
          wx.navigateTo({ url: '/pages/recognize/recognize?kind=meal&camera=1&plan_id=' + this.data.id + '&day=' + day + '&meal=' + meal });
        }
      }
    });
  },

  rate(e) {
    const score = Number(e.currentTarget.dataset.s);
    this.setData({ rating: score });
    this.feedback({ kind: 'rate', score });
  },

  shopping() { wx.navigateTo({ url: '/pages/shopping/shopping?id=' + this.data.id + '&variant=' + this.data.active }); },
  retry() { wx.navigateBack(); }
});
