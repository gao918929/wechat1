const api = require('./utils/api');
const config = require('./config');

function randomId() {
  return 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

App({
  globalData: {
    user: null,
    groups: [],
    groupId: null,
    meta: null
  },

  onLaunch() {
    this.readyPromise = this.login().then(() => this.loadMeta());
  },

  ready() {
    return this.readyPromise || (this.readyPromise = this.login());
  },

  // wx.login → backend code2session. Without WeChat credentials on the backend (local dev),
  // a device-stable dev_id identifies the user instead.
  login() {
    let devId = wx.getStorageSync('dev_id');
    if (!devId) {
      devId = randomId();
      wx.setStorageSync('dev_id', devId);
    }
    const getCode = () => new Promise((resolve) => {
      wx.login({ success: (r) => resolve(r.code || ''), fail: () => resolve('') });
    });
    return getCode().then((code) => api.post('/api/auth/login', { code, dev_id: devId }, { retried: true }))
      .then((data) => {
        api.setToken(data.token);
        this.globalData.user = data.user;
        this.setGroups(data.groups);
        return data;
      });
  },

  loadMeta() {
    return api.get('/api/meta', null, { silent: true }).then((m) => { this.globalData.meta = m; return m; }).catch(() => null);
  },

  setGroups(groups) {
    this.globalData.groups = groups || [];
    const saved = wx.getStorageSync('group_id');
    const exists = this.globalData.groups.some((g) => g.id === saved);
    this.globalData.groupId = exists ? saved : (this.globalData.groups[0] && this.globalData.groups[0].id);
    this.connectSocket();
  },

  refreshGroups() {
    return api.get('/api/me').then((d) => {
      this.globalData.user = d.user;
      this.setGroups(d.groups);
      return d;
    });
  },

  currentGroup() {
    return this.globalData.groups.find((g) => g.id === this.globalData.groupId) || this.globalData.groups[0] || null;
  },

  switchGroup(id) {
    this.globalData.groupId = id;
    wx.setStorageSync('group_id', id);
    this.connectSocket();
  },

  // ---- real-time sync (WebSocket per current group)
  listeners: [],
  onSocket(fn) {
    this.listeners.push(fn);
    return () => { this.listeners = this.listeners.filter((f) => f !== fn); };
  },

  connectSocket() {
    const gid = this.globalData.groupId;
    if (!gid || !api.getToken()) return;
    if (this.socket && this.socketGroup === gid) return;
    if (this.socket) {
      this.socketClosing = true;
      this.socket.close({});
    }
    this.socketGroup = gid;
    this.socketClosing = false;
    const socket = wx.connectSocket({ url: config.wsUrl + '/ws/groups/' + gid + '?token=' + api.getToken() });
    this.socket = socket;
    socket.onMessage((res) => {
      let ev = null;
      try { ev = JSON.parse(res.data); } catch (e) { return; }
      this.listeners.forEach((fn) => fn(ev));
      if (ev.type === 'plan.ready') wx.showToast({ title: '新的膳食计划已生成', icon: 'none' });
    });
    socket.onClose(() => {
      if (this.socket === socket) this.socket = null;
      if (!this.socketClosing && this.socketGroup === gid) setTimeout(() => this.connectSocket(), 3000);
    });
    socket.onError(() => {});
  }
});
