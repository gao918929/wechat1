const api = require('../../utils/api');
const { MEAL, KIND, VARIANT, money } = require('../../utils/util');
const app = getApp();

const LAYER = { hard: '禁忌', inventory: '库存', nutrition: '营养', budget: '预算' };
const WEEK = ['日', '一', '二', '三', '四', '五', '六'];
// each agent is drawn with its pixel sprite /assets/px/sprite-<key>.svg
const AGENTS = [
  { key: 'health', title: '健康适配', role: '营养与安全' },
  { key: 'iterative', title: '迭代优化', role: '数字孪生偏好' },
  { key: 'inventory', title: '库存优先', role: '临期先用' },
  { key: 'budget', title: '预算约束', role: '成本控制' }
];
// one-character badge for the dish category colour block
const KIND_SHORT = { main: '主', veg: '素', soup: '汤', staple: '饭', one_pot: '锅', breakfast: '早' };
// generation progress shown in the loading bar (display only)
function progressOf(doneCount, dayCount) { return Math.min(100, 15 + doneCount * 15 + (dayCount ? 25 : 0)); }
const STAGES = { intent: '解析指令', agent: '智能体分析中', framework: '编排菜单', validation: '三层校验', revision: '退回修订',
  conflict: '生成备选方案', variant: '方案排序', day: '输出菜单', shopping: '生成购物清单', done: '完成' };

function decorateDay(day) {
  const d = new Date(day.date.replace(/-/g, '/'));
  return Object.assign({}, day, {
    dayNum: d.getDate(), week: '周' + WEEK[d.getDay()], month: (d.getMonth() + 1) + '月',
    dishCount: day.meals.reduce((n, m) => n + m.dishes.length, 0),
    costText: money(day.meals.reduce((c, m) => c + (m.cost || 0), 0)),
    meals: day.meals.map((m) => Object.assign({}, m, {
      label: MEAL[m.meal] || m.meal,
      costText: money(m.cost),
      dishes: m.dishes.map((x) => Object.assign({}, x, {
        kindLabel: KIND[x.kind] || x.kind,
        kindShort: KIND_SHORT[x.kind] || String(KIND[x.kind] || x.kind || '菜').slice(0, 1),
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
    id: null, status: 'pending', stage: '排队中', log: [], agents: [], doneCount: 0, progress: 15, intent: null,
    streamDays: [], result: null, variants: [], active: '', variant: null, days: [], chosen: '',
    expanded: {}, showDetails: false, rating: 0, error: '', conflictsText: '', agentRows: []
  },

  onLoad(q) {
    this.setData({ id: Number(q.id) });
    this.agentMap = {};
    this.renderAgents();
    app.ready().then(() => this.start());
    this.off = app.onSocket((ev) => { if (ev.type === 'plan.edited' && ev.plan_id === this.data.id) this.loadPlan(); });
  },

  onUnload() {
    if (this.stream) this.stream.stop();
    if (this.off) this.off();
  },

  start() {
    this.stream = api.streamPlan(this.data.id, 0, (ev) => this.onEvent(ev), (end) => {
      if (end.type === 'done' || end.type === 'error' || end.type === 'failed') this.loadPlan();
    });
  },

  renderAgents() {
    const agents = AGENTS.map((a) => {
      const d = this.agentMap[a.key];
      return Object.assign({}, a, { done: !!d, mode: d && d.mode, summary: d ? d.summary : '', seconds: d ? d.seconds : 0 });
    });
    const doneCount = agents.filter((a) => a.done).length;
    this.setData({ agents, doneCount, progress: progressOf(doneCount, this.data.streamDays.length) });
  },

  addLog(kind, text) {
    this.setData({ log: this.data.log.concat([{ kind, text }]).slice(-30) });
  },

  onEvent(ev) {
    const d = ev.data || {};
    if (STAGES[ev.type]) this.setData({ stage: STAGES[ev.type] });
    if (ev.type === 'intent') {
      const budget = d.budget && d.budget.total ? '预算 ¥' + d.budget.total : '未设预算';
      this.setData({ intent: d, status: 'running' });
      this.addLog('info', d.diners.length + ' 人 · ' + d.days + ' 天 · ' + budget + ' · ' + (d.differentiated ? '差异化多菜' : '全员兼容') +
        (d.hard_constraints.length ? ' · 硬约束 ' + d.hard_constraints.join('、') : ''));
    } else if (ev.type === 'agent') {
      this.agentMap[d.agent] = d;
      this.renderAgents();
    } else if (ev.type === 'framework') {
      this.addLog('info', '总体框架确定，开始编排菜单');
    } else if (ev.type === 'validation') {
      const layers = Object.keys(d.layers).map((k) => LAYER[k] + (d.layers[k].passed ? '✓' : '✗')).join(' ');
      this.addLog(d.passed ? 'ok' : 'warn', VARIANT[d.variant] + '方案 · 第 ' + (d.attempt + 1) + ' 轮校验  ' + layers);
    } else if (ev.type === 'revision') {
      d.rounds.forEach((r) => this.addLog('warn', '退回' + r.title + '：' + (r.applied.length ? r.applied.slice(0, 2).join('；') : '无可行修改')));
    } else if (ev.type === 'conflict') {
      this.addLog('info', '存在取舍：' + d.conflicts.join('；'));
    } else if (ev.type === 'cached') {
      this.addLog('ok', d.message);
    } else if (ev.type === 'variant') {
      this.addLog('ok', d.title + ' · ¥' + money(d.summary.total_cost));
    } else if (ev.type === 'day') {
      const streamDays = this.data.streamDays.concat([decorateDay(d.day)]);
      this.setData({ streamDays, progress: progressOf(this.data.doneCount, streamDays.length) });
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
      const agentRows = AGENTS.map((a) => Object.assign({}, result.agents[a.key] || {}, a));
      this.setData({
        status: 'done', result, chosen: p.chosen_variant, agentRows,
        conflictsText: (result.conflicts || []).join('；'),
        variants: result.variants.map((v) => ({ key: v.key, title: VARIANT[v.key] + (v.recommended ? ' · 推荐' : '') }))
      });
      this.selectVariant(active);
    });
  },

  selectVariant(key) {
    const v = this.data.result.variants.find((x) => x.key === key) || this.data.result.variants[0];
    const s = v.summary;
    const vm = Object.assign({}, v, {
      costText: money(s.total_cost), perPersonText: money(s.per_person_cost),
      usePct: s.budget_utilization ? Math.min(100, Math.round(s.budget_utilization * 100)) : 0,
      // uncapped, so <px-meter> flashes red when the plan is over budget
      budgetPct: s.budget_utilization ? Math.round(s.budget_utilization * 100) : 0,
      costLong: money(s.total_cost).length > 6,
      nearUsed: s.near_expiry_used.map((u) => u.name + ' 第' + u.day + '天'),
      nearUnused: s.near_expiry_unused.map((u) => u.name).join('、'),
      issues: v.validation.issues.slice(0, 6).map((i) => i.message),
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
      itemList: ['收藏这道菜', '换一道', '删除这道菜'],
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
