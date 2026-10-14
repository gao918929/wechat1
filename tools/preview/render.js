// Minimal WXML → HTML renderer for design previews. Not a full WXML implementation: enough for
// this project's pages (wx:if/elif/else, wx:for, {{}} expressions, custom components, slots).
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '../../miniprogram');
const FONTS = path.resolve(__dirname, '../../backend/app/static/fonts');
const APP = JSON.parse(fs.readFileSync(path.join(ROOT, 'app.json'), 'utf8'));
const COMPONENTS = Object.assign({}, APP.usingComponents || {});

function parse(src) {
  const root = { tag: '#root', attrs: {}, children: [] };
  const stack = [root];
  let i = 0;
  while (i < src.length) {
    if (src.startsWith('<!--', i)) { i = src.indexOf('-->', i) + 3; continue; }
    if (src[i] === '<' && src[i + 1] === '/') {
      const end = src.indexOf('>', i); const tag = src.slice(i + 2, end).trim();
      while (stack.length > 1) { const n = stack.pop(); if (n.tag === tag) break; }
      i = end + 1; continue;
    }
    if (src[i] === '<' && /[a-zA-Z]/.test(src[i + 1])) {
      let j = i + 1; while (/[\w-]/.test(src[j])) j++;
      const node = { tag: src.slice(i + 1, j), attrs: {}, children: [] };
      while (true) {
        while (/\s/.test(src[j])) j++;
        if (src[j] === '/' && src[j + 1] === '>') { j += 2; stack[stack.length - 1].children.push(node); break; }
        if (src[j] === '>') { j++; stack[stack.length - 1].children.push(node); stack.push(node); break; }
        let k = j; while (!/[\s=>\/]/.test(src[k])) k++;
        const name = src.slice(j, k); j = k;
        if (src[j] === '=') { const q = src[j + 1]; const e = src.indexOf(q, j + 2); node.attrs[name] = src.slice(j + 2, e); j = e + 1; }
        else node.attrs[name] = 'true';
      }
      i = j; continue;
    }
    const next = src.indexOf('<', i + 1); const text = src.slice(i, next === -1 ? src.length : next);
    if (text.trim()) stack[stack.length - 1].children.push({ tag: '#text', text });
    i = next === -1 ? src.length : next;
  }
  return root;
}

function evalExpr(expr, scope) {
  try { return Function('s', 'with(s){ return (' + expr + ') }')(scope); } catch (e) { return undefined; }
}
function interp(val, scope) {
  const m = /^\s*\{\{([\s\S]*)\}\}\s*$/.exec(val);
  if (m && val.split('{{').length === 2) return evalExpr(m[1], scope);
  return val.replace(/\{\{([\s\S]*?)\}\}/g, (_, e) => { const v = evalExpr(e, scope); return v === undefined || v === null ? '' : v; });
}
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const rpx = (s) => String(s || '').replace(/(-?\d*\.?\d+)rpx/g, (_, n) => (parseFloat(n) / 2) + 'px');
const TAG = { view: 'div', text: 'span', image: 'img', 'scroll-view': 'div', picker: 'div', button: 'div', navigator: 'div', label: 'div' };

function renderChildren(children, scope, slots) {
  let out = ''; let prevIf = null;
  for (const c of children) {
    if (c.tag !== '#text') {
      const a = c.attrs;
      if ('wx:if' in a) { prevIf = !!interp(a['wx:if'], scope); if (!prevIf) continue; }
      else if ('wx:elif' in a) { if (prevIf) continue; prevIf = !!interp(a['wx:elif'], scope); if (!prevIf) continue; }
      else if ('wx:else' in a) { if (prevIf) continue; prevIf = null; }
      else prevIf = null;
    }
    out += renderNode(c, scope, slots);
  }
  return out;
}

function renderNode(n, scope, slots) {
  if (n.tag === '#text') return esc(interp(n.text, scope));
  const a = n.attrs;
  if ('wx:for' in a) {
    const list = interp(a['wx:for'], scope) || [];
    const item = a['wx:for-item'] || 'item'; const index = a['wx:for-index'] || 'index';
    const entries = Array.isArray(list) ? list.map((v, i) => [i, v]) : typeof list === 'number'
      ? Array.from({ length: list }, (_, i) => [i, i]) : Object.entries(list);
    const clone = { ...n, attrs: { ...a } }; delete clone.attrs['wx:for'];
    return entries.map(([k, v]) => renderNode(clone, Object.assign(Object.create(scope), { [item]: v, [index]: k }), slots)).join('');
  }
  if (n.tag === 'slot') return slots[a.name || 'default'] || '';
  if (COMPONENTS[n.tag]) return renderComponent(COMPONENTS[n.tag], n, scope);
  if (n.tag === 'canvas') return '';
  const attrs = {};
  for (const [k, v] of Object.entries(a)) {
    if (k.startsWith('wx:') || k.startsWith('bind') || k.startsWith('catch') || k.startsWith('data-')) continue;
    attrs[k] = interp(v, scope);
  }
  const inner = renderChildren(n.children, scope, slots);
  if (n.tag === 'block') return inner;
  const cls = attrs.class || ''; const style = rpx(attrs.style);
  if (n.tag === 'input') return `<input class="${esc(cls)} wx-input" style="${esc(style)}" value="${esc(attrs.value || '')}" placeholder="${esc(attrs.placeholder || '')}">`;
  if (n.tag === 'textarea') return `<textarea class="${esc(cls)}" style="${esc(style)}" placeholder="${esc(attrs.placeholder || '')}">${esc(attrs.value || '')}</textarea>`;
  if (n.tag === 'switch') return `<span class="wx-switch ${attrs.checked === true || attrs.checked === 'true' ? 'on' : ''}"></span>`;
  if (n.tag === 'slider') return `<span class="wx-slider ${esc(cls)}"><span style="width:${(attrs.value / (attrs.max || 100)) * 100}%"></span></span>`;
  if (n.tag === 'checkbox') return `<span class="wx-checkbox ${attrs.checked === true ? 'on' : ''}"></span>`;
  if (n.tag === 'image') return `<img class="${esc(cls)}" style="${esc(style)}" src="${esc(String(attrs.src || '').replace(/^\//, ROOT + '/'))}">`;
  const tag = TAG[n.tag] || 'div';
  const extra = n.tag === 'scroll-view' ? 'overflow-x:auto;' : '';
  return `<${tag} class="${esc(cls)} wx-${n.tag}" style="${esc(extra + style)}">${inner}</${tag}>`;
}

// ---- components: run their JS (properties, data, observers, attached, finish()) with stubs
function componentData(base, node, scope) {
  const jsPath = path.join(ROOT, base + '.js');
  let def = { properties: {}, data: {} };
  if (fs.existsSync(jsPath)) {
    global.Component = (o) => { def = o; };
    delete require.cache[jsPath];
    require(jsPath);
  }
  const data = {};
  for (const [k, p] of Object.entries(def.properties || {})) data[k] = p && typeof p === 'object' ? p.value : undefined;
  Object.assign(data, JSON.parse(JSON.stringify(def.data || {})));
  for (const [k, v] of Object.entries(node.attrs)) {
    if (k.startsWith('wx:') || k.startsWith('bind') || k === 'slot' || k === 'class' || k === 'style') continue;
    let val = v === 'true' ? true : interp(v, scope);
    const p = (def.properties || {})[k];
    const type = p && typeof p === 'object' ? p.type : p;
    if (type === Number) val = Number(val);
    if (type === Boolean) val = val === true || val === 'true' || (val && val !== 'false');
    data[k] = val;
  }
  const inst = Object.assign({ data }, def.methods || {});
  inst.setData = (patch) => Object.assign(inst.data, patch);
  const saved = global.setInterval; global.setInterval = () => 0;
  try {
    for (const [keys, fn] of Object.entries(def.observers || {})) fn.apply(inst, keys.split(',').map((k) => data[k.trim()]));
    const attached = (def.lifetimes && def.lifetimes.attached) || def.attached;
    if (attached) attached.call(inst);
    if (inst.finish) inst.finish();
  } finally { global.setInterval = saved; }
  return inst.data;
}

function renderComponent(base, node, scope) {
  const src = fs.readFileSync(path.join(ROOT, base + '.wxml'), 'utf8');
  const data = componentData(base, node, scope);
  const slots = {};
  const plain = [];
  for (const c of node.children) {
    if (c.attrs && c.attrs.slot) slots[c.attrs.slot] = renderNode(c, scope, {});
    else plain.push(c);
  }
  slots.default = renderChildren(plain, scope, {});
  const cls = node.attrs.class ? interp(node.attrs.class, scope) : '';
  return `<div class="wx-comp ${esc(cls)}" style="${esc(rpx(interp(node.attrs.style || '', scope)))}">${renderChildren(parse(src).children, data, slots)}</div>`;
}

function css(pageName) {
  const files = [path.join(ROOT, 'app.wxss')];
  for (const base of Object.values(COMPONENTS)) files.push(path.join(ROOT, base + '.wxss'));
  files.push(path.join(ROOT, 'custom-tab-bar/index.wxss'));
  files.push(path.join(ROOT, `pages/${pageName}/${pageName}.wxss`));
  let s = files.map((f) => (fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '')).join('\n');
  s = rpx(s).replace(/\bpage\s*\{/g, 'body {').replace(/env\(safe-area-inset-bottom\)/g, '34px');
  s = s.replace(/(^|[\s,>{}(])image(?=[\s,.:{\[)])/g, '$1img');
  return s.replace(/(^|[\s,>{}(])text(?=[\s,.:{\[)])/g, '$1.wx-text');
}

function page(name, data, opts = {}) {
  const wxml = fs.readFileSync(`${ROOT}/pages/${name}/${name}.wxml`, 'utf8');
  global.wx = global.wx || {};
  global.wx.getWindowInfo = () => ({ statusBarHeight: 44, windowWidth: 375 });
  global.wx.getMenuButtonBoundingClientRect = () => ({ top: 48, height: 32, left: 281 });
  const body = renderChildren(parse(wxml).children, Object.assign({}, data), {});
  let tab = '';
  if (opts.tab !== undefined) {
    const tb = componentData('custom-tab-bar/index', { attrs: {} }, {});
    tb.selected = opts.tab;
    tab = renderChildren(parse(fs.readFileSync(`${ROOT}/custom-tab-bar/index.wxml`, 'utf8')).children, tb, {});
  }
  return `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:"Pixel";src:url("file://${FONTS}/fusion-pixel-12px-sc.woff2") format("woff2")}
@font-face{font-family:"PixelNum";src:url("file://${FONTS}/press-start-2p.woff2") format("woff2")}
*{box-sizing:border-box} body{margin:0;width:375px;min-height:812px;-webkit-font-smoothing:none} div{display:block} span{display:inline}
.wx-comp{display:contents} button{border:0;font:inherit} input,textarea{border:0;font:inherit;outline:0;width:100%;box-sizing:border-box;color:inherit}
.wx-switch{display:inline-block;width:52px;height:30px;background:#e2d3b1;position:relative;box-shadow:0 0 0 2px #2b2340}.wx-switch.on{background:#4cb963}
.wx-switch:after{content:"";position:absolute;top:3px;left:3px;width:24px;height:24px;background:#fffaf0;box-shadow:0 0 0 2px #2b2340}.wx-switch.on:after{left:25px}
.wx-slider{display:inline-block;height:6px;background:#e2d3b1;flex:1}.wx-slider span{display:block;height:6px;background:#4cb963}
.wx-checkbox{display:inline-block;width:22px;height:22px;border:2px solid #2b2340}
img{display:inline-block;image-rendering:pixelated}
${css(name)}</style></head><body>${body}${tab}</body></html>`;
}

module.exports = { page, ROOT };
