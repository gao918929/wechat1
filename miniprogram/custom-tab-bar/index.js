// Floating frosted-glass tab bar (tabBar.custom = true in app.json).
Component({
  data: {
    selected: 0,
    list: [
      { pagePath: '/pages/index/index', text: '首页', icon: 'home' },
      { pagePath: '/pages/inventory/inventory', text: '冰箱', icon: 'fridge' },
      { pagePath: '/pages/planner/planner', text: '计划', icon: 'plan' },
      { pagePath: '/pages/budget/budget', text: '账本', icon: 'wallet' },
      { pagePath: '/pages/profile/profile', text: '我的', icon: 'person' }
    ]
  },
  methods: {
    switchTab(e) {
      const i = e.currentTarget.dataset.index;
      if (i === this.data.selected) return;
      wx.vibrateShort && wx.vibrateShort({ type: 'light' });
      wx.switchTab({ url: this.data.list[i].pagePath });
    }
  }
});
