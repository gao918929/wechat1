const api = require('../../utils/api');
const app = getApp();

Page({
  data: { items: [] },
  onShow() { app.ready().then(() => this.load()); },
  load() { return api.get('/api/notifications').then((r) => this.setData({ items: r.items.map((i) => Object.assign(i, { time: i.created_at.slice(5, 16).replace('T', ' ') })) })); },
  open(e) {
    const n = this.data.items[e.currentTarget.dataset.index];
    api.post('/api/notifications/' + n.id + '/read', {}, { silent: true });
    if (n.link) wx.navigateTo({ url: n.link });
  }
});
