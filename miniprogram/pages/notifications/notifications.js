const api = require('../../utils/api');
const app = getApp();

// display-only: pick a pixel icon + tile colour for a notification from its link / title
function iconFor(n) {
  const s = (n.link || '') + ' ' + (n.title || '');
  if (/shopping|购物/.test(s)) return { icon: 'cart', tone: 'i-blue' };
  if (/budget|预算|账/.test(s)) return { icon: 'coin', tone: 'i-yellow' };
  if (/inventory|到期|临期|过期/.test(s)) return { icon: 'clock', tone: 'i-orange' };
  if (/group|小组|成员/.test(s)) return { icon: 'users', tone: '' };
  if (/plan|计划/.test(s)) return { icon: 'magic', tone: 'i-purple' };
  return { icon: 'bell', tone: 'i-yellow' };
}

Page({
  data: { items: [], unread: 0 },
  onShow() { app.ready().then(() => this.load()); },
  load() {
    return api.get('/api/notifications').then((r) => {
      let blinking = 0; // only the first two unread dots blink (keep looping animations per screen ≤ 3)
      const items = r.items.map((i) => Object.assign(i, { time: i.created_at.slice(5, 16).replace('T', ' ') }, iconFor(i),
        { blink: !i.read && blinking++ < 2 }));
      this.setData({ items, unread: items.filter((i) => !i.read).length });
    });
  },
  open(e) {
    const n = this.data.items[e.currentTarget.dataset.index];
    api.post('/api/notifications/' + n.id + '/read', {}, { silent: true });
    if (n.link) wx.navigateTo({ url: n.link });
  }
});
