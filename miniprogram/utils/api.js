// HTTP / upload / SSE helpers for the MealAgent backend.
const config = require('../config');

let token = wx.getStorageSync('token') || '';

function setToken(t) {
  token = t;
  wx.setStorageSync('token', t);
}

function getToken() {
  return token;
}

function errorMessage(res) {
  const d = res.data && res.data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d.length) return d[0].msg || '参数错误';
  return '请求失败（' + res.statusCode + '）';
}

function request(method, path, data, opts) {
  opts = opts || {};
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.baseUrl + path,
      method,
      data,
      timeout: opts.timeout || 60000,
      header: { 'content-type': 'application/json', Authorization: token ? 'Bearer ' + token : '' },
      success(res) {
        if (res.statusCode === 401 && !opts.retried) {
          getApp().login().then(() => request(method, path, data, Object.assign({}, opts, { retried: true }))).then(resolve, reject);
          return;
        }
        if (res.statusCode >= 400) {
          const msg = errorMessage(res);
          if (!opts.silent) wx.showToast({ title: msg.slice(0, 40), icon: 'none' });
          reject(new Error(msg));
          return;
        }
        resolve(res.data);
      },
      fail(err) {
        if (!opts.silent) wx.showToast({ title: '网络错误：请确认后端已启动', icon: 'none' });
        reject(err);
      }
    });
  });
}

function upload(path, filePath, formData) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: config.baseUrl + path,
      filePath,
      name: 'file',
      formData,
      timeout: 120000,
      header: { Authorization: 'Bearer ' + token },
      success(res) {
        let data = {};
        try { data = JSON.parse(res.data); } catch (e) { /* ignore */ }
        if (res.statusCode >= 400) {
          const msg = (data && data.detail) || '上传失败';
          wx.showToast({ title: String(msg).slice(0, 40), icon: 'none' });
          reject(new Error(msg));
          return;
        }
        resolve(data);
      },
      fail(err) {
        wx.showToast({ title: '上传失败', icon: 'none' });
        reject(err);
      }
    });
  });
}

// Incremental UTF-8 decoder (chunks may split a multi-byte character).
function utf8Decode(bytes) {
  let out = '';
  let i = 0;
  while (i < bytes.length) {
    const c = bytes[i];
    const n = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
    if (i + n > bytes.length) break;
    let cp;
    if (n === 1) cp = c;
    else if (n === 2) cp = ((c & 0x1f) << 6) | (bytes[i + 1] & 0x3f);
    else if (n === 3) cp = ((c & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f);
    else cp = ((c & 0x07) << 18) | ((bytes[i + 1] & 0x3f) << 12) | ((bytes[i + 2] & 0x3f) << 6) | (bytes[i + 3] & 0x3f);
    out += String.fromCodePoint(cp);
    i += n;
  }
  return { text: out, rest: bytes.slice(i) };
}

// Stream plan-generation progress. Uses SSE over chunked wx.request; falls back to polling
// (also used to resume after the page is reopened or the connection drops).
function streamPlan(planId, since, onEvent, onEnd) {
  let closed = false;
  let last = since - 1;
  let pollTimer = null;
  let task = null;

  function stop() {
    closed = true;
    if (pollTimer) clearTimeout(pollTimer);
    if (task && task.abort) {
      try { task.abort(); } catch (e) { /* ignore */ }
    }
  }

  function handle(ev) {
    if (closed || ev.type === 'ping') return;
    if (ev.seq !== undefined && ev.seq <= last) return;
    if (ev.seq !== undefined) last = ev.seq;
    onEvent(ev);
    if (ev.type === 'done' || ev.type === 'error') {
      stop();
      if (onEnd) onEnd(ev);
    }
  }

  function poll() {
    if (closed) return;
    request('GET', '/api/plans/' + planId + '?since=' + (last + 1), null, { silent: true }).then((p) => {
      (p.events || []).forEach(handle);
      if (closed) return;
      if (p.status === 'done' || p.status === 'failed') {
        stop();
        if (onEnd) onEnd({ type: p.status });
      } else {
        pollTimer = setTimeout(poll, 1500);
      }
    }).catch(() => { pollTimer = setTimeout(poll, 3000); });
  }

  let buffer = '';
  let pending = new Uint8Array(0);
  try {
    task = wx.request({
      url: config.baseUrl + '/api/plans/' + planId + '/stream?since=' + since,
      method: 'GET',
      enableChunked: true,
      responseType: 'arraybuffer',
      timeout: 300000,
      header: { Authorization: 'Bearer ' + token, Accept: 'text/event-stream' },
      complete() { if (!closed) poll(); }
    });
  } catch (e) {
    task = null;
  }
  if (!task || typeof task.onChunkReceived !== 'function') {
    poll();
    return { stop };
  }
  task.onChunkReceived((res) => {
    const chunk = new Uint8Array(res.data);
    const merged = new Uint8Array(pending.length + chunk.length);
    merged.set(pending, 0);
    merged.set(chunk, pending.length);
    const decoded = utf8Decode(merged);
    pending = decoded.rest;
    buffer += decoded.text;
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = block.split('\n').filter((l) => l.indexOf('data: ') === 0).map((l) => l.slice(6)).join('');
      if (!dataLine) continue;
      try { handle(JSON.parse(dataLine)); } catch (e) { /* partial or malformed block */ }
    }
  });
  return { stop };
}

module.exports = {
  setToken,
  getToken,
  request,
  get: (p, d, o) => request('GET', p, d, o),
  post: (p, d, o) => request('POST', p, d, o),
  put: (p, d, o) => request('PUT', p, d, o),
  del: (p, d, o) => request('DELETE', p, d, o),
  upload,
  streamPlan
};
