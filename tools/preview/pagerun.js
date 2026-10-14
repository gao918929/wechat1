// Run a page's real JS against stubbed wx / getApp / utils/api to obtain its view data.
const path = require('path');
const { ROOT } = require('./render');

function setPath(obj, p, v) {
  const keys = p.replace(/\[(\d+)\]/g, '.$1').split('.');
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) { o[keys[i]] = o[keys[i]] || {}; o = o[keys[i]]; }
  o[keys[keys.length - 1]] = v;
}
const tick = () => new Promise((r) => setTimeout(r, 5));

async function runPage(name, { query = {}, responses = {}, events = [], end = true, app: appData = {}, after } = {}) {
  global.wx = new Proxy({
    getStorageSync: () => '', setStorageSync() {},
    getWindowInfo: () => ({ statusBarHeight: 44, windowWidth: 375 }),
    getMenuButtonBoundingClientRect: () => ({ top: 48, height: 32, left: 281 }),
    canIUse: () => true
  }, { get: (t, k) => (k in t ? t[k] : () => {}) });
  const fakeApp = Object.assign({
    globalData: {}, ready: () => Promise.resolve(), onSocket: () => () => {},
    currentGroup() { return this.globalData.groups[0]; }, refreshGroups: () => Promise.resolve(),
    loadMeta() { return Promise.resolve(this.globalData.meta); }, switchGroup() {}
  }, appData);
  global.getApp = () => fakeApp;
  let def; global.Page = (o) => { def = o; };
  const apiPath = path.join(ROOT, 'utils/api.js');
  const keys = Object.keys(responses).sort((a, b) => b.length - a.length); // longest prefix wins
  const find = (p) => { const k = keys.find((r) => p.indexOf(r) === 0); return k ? JSON.parse(JSON.stringify(responses[k])) : {}; };
  require.cache[apiPath] = { id: apiPath, filename: apiPath, loaded: true, exports: {
    get: (p) => Promise.resolve(find(p)), post: (p) => Promise.resolve(find(p)), put: (p) => Promise.resolve(find(p)),
    del: () => Promise.resolve({}), request: (m, p) => Promise.resolve(find(p)), upload: () => new Promise(() => {}),
    getToken: () => 't', setToken() {},
    streamPlan: (id, since, onEvent, onEnd) => { events.forEach(onEvent); if (end && onEnd) onEnd({ type: 'done' }); return { stop() {} }; } } };
  const pagePath = path.join(ROOT, `pages/${name}/${name}.js`);
  for (const k of Object.keys(require.cache)) if (k.startsWith(path.join(ROOT, 'pages'))) delete require.cache[k];
  require(pagePath);
  const inst = Object.assign({}, def, { data: JSON.parse(JSON.stringify(def.data || {})) });
  inst.setData = (patch, cb) => { for (const [k, v] of Object.entries(patch)) setPath(inst.data, k, v); if (cb) cb(); };
  inst.getTabBar = () => null;
  inst.selectComponent = () => null;
  if (inst.onLoad) inst.onLoad(query);
  if (inst.onShow) inst.onShow();
  for (let i = 0; i < 6; i++) await tick();
  if (after) { after(inst); for (let i = 0; i < 6; i++) await tick(); }
  return inst.data;
}
module.exports = { runPage };
