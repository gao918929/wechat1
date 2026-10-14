const api = require('../../utils/api');
const { money, iconFor, initialOf } = require('../../utils/util');
const app = getApp();
// pixel icon shown in each section's window title bar
const SECTION_ICON = { vegetables: 'broccoli', meat_eggs: 'meat', seafood: 'fish', soy_dairy: 'milk', staples: 'meal', seasonings: 'chili' };

Page({
  data: {
    id: null, variant: '', title: '', shopping: null, checked: {}, totalText: '', perText: '', canvasH: 600,
    // display-only: quest progress + budget summary
    totalCls: '', leftText: '', overText: '', secDone: {}, doneCount: 0, itemCount: 0, donePct: 0
  },

  onLoad(q) {
    this.setData({ id: Number(q.id), variant: q.variant || '' });
    app.ready().then(() => this.load());
    this.off = app.onSocket((ev) => {
      if (ev.type === 'shopping.checked' && ev.plan_id === this.data.id && ev.variant === this.data.variant) {
        this.setData({ ['checked.' + ev.name]: ev.checked });
        this.tally();
      }
    });
  },

  onUnload() { if (this.off) this.off(); },

  load() {
    const q = this.data.variant ? '?variant=' + this.data.variant : '';
    return api.get('/api/plans/' + this.data.id + '/shopping' + q).then((r) => {
      const s = r.shopping;
      s.sections.forEach((sec) => {
        sec.icon = SECTION_ICON[sec.section] || 'cart';
        // display-only: ingredient icon (shared rules in utils/util.js) or its initial
        sec.items.forEach((it) => { it.costText = money(it.cost); it.icon = iconFor(it.name); it.initial = initialOf(it.name); });
      });
      this.setData({
        variant: r.variant, title: r.title, shopping: r.shopping, checked: r.checked || {},
        totalText: money(r.shopping.total_cost), perText: money(r.shopping.per_person_cost),
        pantryText: r.shopping.pantry.map((p) => p.name).join('、'),
        coveredText: r.shopping.covered_by_inventory.map((c) => c.name).join('、'),
        totalCls: money(s.total_cost).length > 6 ? 'long' : '',
        leftText: s.budget_total ? money(Math.max(0, s.budget_total - s.total_cost)) : '',
        overText: money(s.over_amount)
      });
      this.tally();
    });
  },

  // Count ticked items (overall and per section) for the quest progress meter.
  tally() {
    const s = this.data.shopping;
    if (!s) return;
    const checked = this.data.checked || {};
    const secDone = {};
    let done = 0;
    let total = 0;
    s.sections.forEach((sec) => {
      const n = sec.items.filter((it) => checked[it.name]).length;
      secDone[sec.section] = n;
      done += n;
      total += sec.items.length;
    });
    this.setData({ secDone, doneCount: done, itemCount: total, donePct: total ? done / total * 100 : 0 });
  },

  toggle(e) {
    const name = e.currentTarget.dataset.name;
    const checked = !this.data.checked[name];
    this.setData({ ['checked.' + name]: checked });
    this.tally();
    api.post('/api/plans/' + this.data.id + '/shopping/check', { variant: this.data.variant, name, checked }, { silent: true });
  },

  copyText() {
    api.get('/api/plans/' + this.data.id + '/shopping/text?variant=' + this.data.variant).then((text) => {
      wx.setClipboardData({ data: String(text) });
    });
  },

  // Render the list onto a canvas and offer the image for saving / sharing.
  makeImage() {
    const s = this.data.shopping;
    const lines = [{ t: 'MealAgent 购物清单', size: 20, bold: true }, { t: this.data.title, size: 13, color: '#7a8580' }];
    s.sections.forEach((sec) => {
      lines.push({ t: '— ' + sec.label + ' —', size: 15, bold: true, gap: 8 });
      sec.items.forEach((it) => lines.push({ t: (this.data.checked[it.name] ? '☑ ' : '□ ') + it.name + '  ' + it.qty_text + '  ¥' + money(it.cost) + (it.price_estimated ? '（估）' : ''), size: 14 }));
    });
    lines.push({ t: '合计 ¥' + this.data.totalText + '  人均 ¥' + this.data.perText, size: 16, bold: true, gap: 10 });
    if (s.over_budget) lines.push({ t: '超出预算 ¥' + money(s.over_amount), size: 14, color: '#c94a4a' });
    if (s.pantry.length) lines.push({ t: '常备调料检查：' + this.data.pantryText, size: 12, color: '#7a8580' });
    const width = 360;
    const height = 40 + lines.reduce((h, l) => h + l.size + 12 + (l.gap || 0), 0);
    this.setData({ canvasH: height }, () => {
      wx.createSelectorQuery().select('#shot').fields({ node: true, size: true }).exec((res) => {
        if (!res[0] || !res[0].node) return wx.showToast({ title: '当前基础库不支持生成图片', icon: 'none' });
        const canvas = res[0].node;
        const dpr = wx.getWindowInfo ? wx.getWindowInfo().pixelRatio : 2;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);
        let y = 24;
        lines.forEach((l) => {
          y += (l.gap || 0) + l.size;
          ctx.font = (l.bold ? 'bold ' : '') + l.size + 'px sans-serif';
          ctx.fillStyle = l.color || '#1f2a24';
          ctx.fillText(l.t, 20, y);
          y += 12;
        });
        wx.canvasToTempFilePath({
          canvas,
          success: (r) => wx.previewImage({ urls: [r.tempFilePath] }),
          fail: () => wx.showToast({ title: '生成图片失败', icon: 'none' })
        });
      });
    });
  }
});
