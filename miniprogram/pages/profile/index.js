const api = require("../../utils/api");
const allergens = [
  ["egg", "鸡蛋"],
  ["milk", "乳"],
  ["peanut", "花生"],
  ["tree_nut", "坚果"],
  ["soy", "大豆"],
  ["wheat", "小麦"],
  ["fish", "鱼"],
  ["shellfish", "甲壳 / 贝类"],
  ["sesame", "芝麻"],
  ["mango", "芒果"],
];
const tags = [
  ["student", "学生"],
  ["family", "家庭"],
  ["stomach_friendly", "养胃清淡"],
  ["chronic", "慢病"],
  ["pregnant", "孕期"],
  ["lactating", "哺乳期"],
  ["child", "儿童"],
  ["fitness", "健身"],
  ["vegetarian", "素食"],
  ["halal", "清真"],
];
Page({
  data: {
    profile: {},
    sexes: ["未设置", "女性", "男性"],
    sexIndex: 0,
    goals: ["维持", "减脂", "增肌", "清淡"],
    goalIndex: 0,
    allergens: [],
    tags: [],
    catalog: [],
    forbidden: [],
    dislikes: "",
    likes: "",
    target: "",
    busy: false,
  },
  onShow: api.guard(async function () {
    const s = await api.ready();
    if (!s) return;
    const me = await api.request("/me"),
      p = me.profile;
    this.setData({
      profile: p,
      name: me.name,
      catalog: s.catalog,
      sexIndex: ["unspecified", "female", "male"].indexOf(p.sex),
      goalIndex: [
        "maintenance",
        "fat_loss",
        "muscle_gain",
        "stomach_friendly",
      ].indexOf(p.goal),
      allergens: allergens.map(([id, name]) => ({
        id,
        name,
        checked: p.allergens.includes(id),
      })),
      tags: tags.map(([id, name]) => ({
        id,
        name,
        checked: p.tags.includes(id),
      })),
      forbidden: s.catalog.map((f) => ({
        ...f,
        checked: p.forbidden_ingredients.includes(f.id),
      })),
      dislikes: p.dislikes.join(","),
      likes: p.likes.join(","),
      target: p.meal_target ? JSON.stringify(p.meal_target, null, 2) : "",
    });
  }),
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  check(e) {
    this.setData({
      ["profile." + e.currentTarget.dataset.key]: e.detail.value,
    });
  },
  save: api.guard(async function () {
    this.setData({ busy: true });
    const p = { ...this.data.profile };
    for (const key of ["height_cm", "weight_kg", "body_fat_pct", "age"])
      p[key] = p[key] === "" || p[key] === null ? null : Number(p[key]);
    p.sex = ["unspecified", "female", "male"][Number(this.data.sexIndex)];
    p.goal = ["maintenance", "fat_loss", "muscle_gain", "stomach_friendly"][
      Number(this.data.goalIndex)
    ];
    p.dislikes = this.data.dislikes
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    p.likes = this.data.likes
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    p.meal_target = this.data.target.trim()
      ? JSON.parse(this.data.target)
      : null;
    await api.request("/me/profile", "PUT", p);
    wx.showToast({ title: "画像已更新" });
  }),
  autoTarget: api.guard(async function () {
    const result = await api.request("/me/target");
    wx.showModal({
      title: "当前每餐目标",
      content: JSON.stringify(result.target),
      showCancel: false,
    });
  }),
  template() {
    this.setData({
      target: JSON.stringify(
        {
          kcal_min: 400,
          kcal_max: 800,
          protein_min: 20,
          protein_max: 60,
          carbs_min: 35,
          carbs_max: 110,
          fat_min: 8,
          fat_max: 30,
        },
        null,
        2,
      ),
    });
    wx.showModal({
      title: "仅为字段示例",
      content:
        "这些数字不是给你的医学建议。请逐项改成你或专业人员确认的目标后保存。",
      showCancel: false,
    });
  },
  twin() {
    wx.navigateTo({ url: "/pages/twin/index" });
  },
  invite: api.guard(async function () {
    const r = await api.request(api.groupPath("/invite"), "POST", {});
    wx.setClipboardData({ data: r.invite_code });
  }),
  logout: api.guard(async function () {
    await api.request("/auth/logout", "POST", {});
    wx.removeStorageSync("token");
    wx.removeStorageSync("group");
    getApp().globalData.token = "";
    getApp().globalData.group = null;
    wx.navigateTo({ url: "/pages/login/index" });
  }),
});
