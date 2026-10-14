const api = require('../../utils/api');
const config = require('../../config');
const { money } = require('../../utils/util');
const app = getApp();

const EXAMPLES = [
  '我在减脂，身高175cm体重72kg，宿舍4个人，这周伙食预算每人80元，我不吃辣不吃海鲜，冰箱里有番茄、鸡蛋和快过期的鸡胸肉，帮我们规划一周减脂晚餐',
  '一家三口，有一位孕妇，孩子5岁，下周午餐和晚餐，总预算400元，清淡少油',
  '宿舍3个人想省钱，每人每周60元，帮我安排5天的午饭'
];
const EXAMPLE_TITLES = ['宿舍减脂晚餐', '孕妇+孩子的家常餐', '省钱午饭'];
// quest-card dressing (display only): pixel icon + one-line brief of each example
const EXAMPLE_ICONS = ['flame', 'heart', 'coin'];
const EXAMPLE_META = ['4 人 · 7 天晚餐 · 人均 ¥80', '3 人 · 午餐+晚餐 · 共 ¥400', '3 人 · 5 天午饭 · 人均 ¥60'];

Page({
  data: {
    group: null,
    instruction: '',
    examples: EXAMPLES.map((text, i) => ({ text, title: EXAMPLE_TITLES[i], icon: EXAMPLE_ICONS[i], meta: EXAMPLE_META[i] })),
    days: 7,
    dayOptions: [1, 2, 3, 4, 5, 6, 7, 14],
    meals: { breakfast: false, lunch: false, dinner: true },
    people: '',
    alternatives: true,
    avoidances: [],
    overrides: {},
    plans: [],
    submitting: false
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) this.getTabBar().setData({ selected: 2 });
    app.ready().then(() => this.load());
  },

  onPullDownRefresh() { this.load().then(() => wx.stopPullDownRefresh()); },

  load() {
    const group = app.currentGroup();
    const user = app.globalData.user || {};
    const meta = app.globalData.meta || {};
    const labels = {};
    (meta.avoid_options || []).concat(meta.allergen_options || []).forEach((o) => { labels[o.key] = o.label; });
    this.setData({ group, avoidances: (user.avoidances || []).map((k) => ({ key: k, label: labels[k] || k })) });
    if (!group) return Promise.resolve();
    return api.get('/api/groups/' + group.id + '/plans').then((plans) => this.setData({
      plans: plans.map((x) => Object.assign(x, {
        dateText: x.created_at.slice(5, 10).replace('-', '/'),
        state: x.status === 'done' ? 'ok' : x.status === 'failed' ? 'danger' : 'warn',
        stateText: x.status === 'done' ? '已完成' : x.status === 'failed' ? '失败' : '生成中',
        // quest-log display fields
        dateMon: Number(x.created_at.slice(5, 7)) + '月',
        dateDay: x.created_at.slice(8, 10),
        stateIcon: x.status === 'done' ? 'check' : x.status === 'failed' ? 'cross' : 'clock',
        costText: x.summary ? money(x.summary.total_cost) : '',
        perText: x.summary ? money(x.summary.per_person_cost) : ''
      }))
    }));
  },

  onInput(e) { this.setData({ instruction: e.detail.value }); },
  useExample(e) { this.setData({ instruction: this.data.examples[e.currentTarget.dataset.i].text }); },
  onDays(e) { this.setData({ days: this.data.dayOptions[e.detail.value] }); },
  toggleMeal(e) {
    const k = e.currentTarget.dataset.k;
    this.setData({ ['meals.' + k]: !this.data.meals[k] });
  },
  onPeople(e) { this.setData({ people: e.detail.value }); },
  // bound to the pixel toggle (tap → flip); still accepts a switch-style change event ({ value })
  onAlt(e) { this.setData({ alternatives: e && e.detail && typeof e.detail.value === 'boolean' ? e.detail.value : !this.data.alternatives }); },
  toggleOverride(e) {
    const k = e.currentTarget.dataset.k;
    this.setData({ ['overrides.' + k]: !this.data.overrides[k] });
  },

  subscribe() {
    if (!config.planTemplateId) return Promise.resolve();
    return new Promise((resolve) => wx.requestSubscribeMessage({ tmplIds: [config.planTemplateId], complete: resolve }));
  },

  submit() {
    const meals = Object.keys(this.data.meals).filter((k) => this.data.meals[k]);
    if (!meals.length) return wx.showToast({ title: '至少选择一个餐次', icon: 'none' });
    const body = {
      instruction: this.data.instruction.trim(),
      days: this.data.days,
      meals,
      alternatives: this.data.alternatives ? 'always' : 'auto',
      overrides: Object.keys(this.data.overrides).filter((k) => this.data.overrides[k])
    };
    if (this.data.people) body.people = Number(this.data.people);
    this.setData({ submitting: true });
    this.subscribe().then(() => api.post('/api/groups/' + this.data.group.id + '/plans', body)).then((r) => {
      this.setData({ submitting: false });
      wx.navigateTo({ url: '/pages/plan/plan?id=' + r.id });
    }).catch(() => this.setData({ submitting: false }));
  },

  open(e) { wx.navigateTo({ url: '/pages/plan/plan?id=' + e.currentTarget.dataset.id }); }
});
