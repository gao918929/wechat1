const api = require('../../utils/api');
const { metaLabels } = require('../../utils/util');
const app = getApp();

const VIS = [{ key: 'owner', label: '仅创建者' }, { key: 'selected', label: '指定成员' }, { key: 'all', label: '全部成员' }];
// display-only helpers (pixel roster)
const KIND_LABEL = { dorm: '宿舍', household: '家庭', personal: '个人' };
const TONES = ['tone-green', 'tone-blue', 'tone-orange', 'tone-purple', 'tone-pink'];

Page({
  data: { groups: [], current: null, detail: null, isAdmin: false, isOwner: false, newName: '', newKind: 'dorm', code: '', vis: VIS, me: null,
    kindLabel: '', codeChars: [], adminCount: 0, dietCount: 0 },

  onShow() { app.ready().then(() => this.load()); },

  load() {
    return app.refreshGroups().then(() => {
      const current = app.currentGroup();
      this.setData({ groups: app.globalData.groups, current, me: app.globalData.user });
      return api.get('/api/groups/' + current.id);
    }).then((detail) => {
      const me = app.globalData.user.id;
      const visible = detail.twin_visible_member_ids || [];
      detail.member_list.forEach((m) => { m.visible = visible.indexOf(m.id) >= 0; m.isMe = m.id === me; });
      // display fields: avatar initial / colour, readable diet labels, party stats, invite-code cells
      const diet = {};
      detail.member_list.forEach((m, i) => {
        // Chinese nicknames share prefixes (小明 / 小红), so show the last character; otherwise the first letter
        const chars = Array.from(m.nickname || '?');
        m.initial = chars.length > 1 && /[\u4e00-\u9fff]/.test(chars[0]) ? chars[chars.length - 1] : chars[0].toUpperCase();
        m.tone = TONES[i % TONES.length];
        m.allergenText = metaLabels('allergen_options', m.allergens);
        m.avoidText = metaLabels('avoid_options', m.avoidances);
        (m.allergens || []).concat(m.avoidances || []).forEach((a) => { diet[a] = 1; });
      });
      this.setData({ detail, isAdmin: detail.role === 'admin', isOwner: detail.owner_id === me,
        kindLabel: KIND_LABEL[detail.kind] || '小组',
        codeChars: Array.from(String(detail.invite_code || '')),
        adminCount: detail.member_list.filter((m) => m.role === 'admin').length,
        dietCount: Object.keys(diet).length });
    });
  },

  switchTo(e) {
    app.switchGroup(Number(e.currentTarget.dataset.id));
    this.load();
  },

  onName(e) { this.setData({ newName: e.detail.value }); },
  setKind(e) { this.setData({ newKind: e.currentTarget.dataset.k }); },
  create() {
    if (!this.data.newName.trim()) return wx.showToast({ title: '请输入名称', icon: 'none' });
    api.post('/api/groups', { name: this.data.newName.trim(), kind: this.data.newKind }).then((g) => {
      app.switchGroup(g.id);
      this.setData({ newName: '' });
      this.load();
    });
  },

  onCode(e) { this.setData({ code: e.detail.value }); },
  join() {
    api.post('/api/groups/join', { invite_code: this.data.code }).then((g) => {
      app.switchGroup(g.id);
      wx.showToast({ title: '已加入 ' + g.name });
      this.setData({ code: '' });
      this.load();
    });
  },

  copyCode() { wx.setClipboardData({ data: this.data.detail.invite_code }); },

  memberActions(e) {
    const m = this.data.detail.member_list[e.currentTarget.dataset.index];
    if (!this.data.isAdmin || m.isMe) return;
    const items = [m.role === 'admin' ? '设为普通成员' : '设为管理员', '移出小组'];
    if (this.data.isOwner && this.data.detail.twin_visibility === 'selected') items.push(m.visible ? '取消查看群体孪生' : '允许查看群体孪生');
    wx.showActionSheet({
      itemList: items,
      success: (r) => {
        const gid = this.data.detail.id;
        if (r.tapIndex === 0) api.put('/api/groups/' + gid + '/members/' + m.id, { role: m.role === 'admin' ? 'member' : 'admin' }).then(() => this.load());
        if (r.tapIndex === 1) api.del('/api/groups/' + gid + '/members/' + m.id).then(() => this.load());
        if (r.tapIndex === 2) {
          const ids = (this.data.detail.twin_visible_member_ids || []).filter((x) => x !== m.id);
          if (!m.visible) ids.push(m.id);
          api.put('/api/groups/' + gid, { twin_visible_member_ids: ids }).then(() => this.load());
        }
      }
    });
  },

  setVis(e) {
    api.put('/api/groups/' + this.data.detail.id, { twin_visibility: e.currentTarget.dataset.k }).then(() => this.load());
  },

  leave() {
    const me = app.globalData.user.id;
    wx.showModal({
      title: '退出小组？',
      success: (r) => {
        if (!r.confirm) return;
        api.del('/api/groups/' + this.data.detail.id + '/members/' + me).then(() => {
          const other = this.data.groups.find((g) => g.id !== this.data.detail.id);
          if (other) app.switchGroup(other.id);
          this.load();
        });
      }
    });
  }
});
