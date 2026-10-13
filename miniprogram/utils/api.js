function app() {
  return getApp();
}
function base() {
  return (wx.getStorageSync("apiBase") || "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
}
function message(data) {
  if (!data) return "网络请求失败";
  const d = data.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
  return typeof d === "string" ? d : "请求失败，请稍后重试";
}
function request(path, method = "GET", data) {
  return new Promise((resolve, reject) =>
    wx.request({
      url: base() + "/api" + path,
      method,
      data,
      timeout: 200000,
      header: {
        Authorization: "Bearer " + app().globalData.token,
        "Content-Type": "application/json",
      },
      success: (r) => {
        if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data);
        else {
          if (r.statusCode === 401) {
            app().globalData.token = "";
            wx.removeStorageSync("token");
          }
          reject(new Error(message(r.data)));
        }
      },
      fail: () =>
        reject(new Error("无法连接后端，请检查服务器地址与合法域名配置")),
    }),
  );
}
async function ready() {
  if (!app().globalData.token) {
    wx.navigateTo({ url: "/pages/login/index" });
    return false;
  }
  const groups = await request("/groups");
  let group =
    groups.find(
      (g) => app().globalData.group && g.id === app().globalData.group.id,
    ) ||
    groups[0] ||
    null;
  app().globalData.group = group;
  wx.setStorageSync("group", group);
  if (!app().globalData.catalog.length)
    app().globalData.catalog = await request("/catalog");
  return { group, groups, catalog: app().globalData.catalog };
}
function groupPath(path = "") {
  const group = app().globalData.group;
  if (!group) throw new Error("请先在首页创建或加入家庭 / 宿舍");
  return "/groups/" + group.id + path;
}
function guard(fn) {
  return async function (...args) {
    try {
      return await fn.apply(this, args);
    } catch (e) {
      wx.showModal({
        title: "请检查",
        content: e.message || String(e),
        showCancel: false,
      });
    } finally {
      if (this.setData) this.setData({ busy: false });
    }
  };
}
function ask(title, placeholder = "") {
  return new Promise((resolve) =>
    wx.showModal({
      title,
      editable: true,
      placeholderText: placeholder,
      success: (r) => resolve(r.confirm ? r.content : null),
      fail: () => resolve(null),
    }),
  );
}
function id() {
  return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
}
function today(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, "0"),
    String(d.getDate()).padStart(2, "0"),
  ].join("-");
}
function live(onChange) {
  if (!app().globalData.group) return () => {};
  const socket = wx.connectSocket({
    url: base().replace(/^http/, "ws") + "/api" + groupPath("/live"),
  });
  socket.onOpen(() =>
    socket.send({ data: JSON.stringify({ token: app().globalData.token }) }),
  );
  socket.onMessage(({ data }) => {
    try {
      const e = JSON.parse(data);
      if (e.type === "ping") socket.send({ data: "pong" });
      else if (e.type !== "ready") onChange(e);
    } catch (_) {}
  });
  socket.onError(() => {});
  return () => socket.close();
}
function money(cents) {
  return (Number(cents || 0) / 100).toFixed(2);
}
module.exports = {
  request,
  ready,
  groupPath,
  guard,
  ask,
  id,
  today,
  base,
  live,
  money,
};
