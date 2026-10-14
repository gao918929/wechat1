const MEAL = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' };
const KIND = { main: '主菜', veg: '素菜', soup: '汤', staple: '主食', one_pot: '一锅出', breakfast: '早餐' };
const LEVEL_TAG = { ok: '', near_expiry: 'warn', expired: 'danger', not_fresh: 'danger' };
const VARIANT = { balanced: '平衡', health: '健康优先', budget: '预算优先' };
const AGENT_ICON = { health: '🩺', inventory: '🧊', budget: '💰', iterative: '🔁' };

// ---- ingredient → pixel icon (/assets/px/<icon>.svg); shared by inventory, recognize, shopping …
// Each rule is [icon, keywords]. An empty icon '' is a "stop" rule: it claims names such as 酱油 / 玉米 / 面包 so a
// shorter keyword inside them (油 / 米 / 面) does not give them the wrong icon.
const ICON_RULES = [
  ['', ['酱油', '蚝油', '玉米', '花生', '米醋', '米酒', '面包', '面粉', '蛋糕']],
  ['egg', ['蛋']],
  ['tomato', ['番茄', '西红柿', '圣女果']],
  ['carrot', ['胡萝卜', '红萝卜']],
  ['broccoli', ['西兰花', '西蓝花', '花椰菜', '花菜']],
  ['milk', ['牛奶', '酸奶', '奶粉']],
  ['fish', ['鱼']],
  ['chili', ['辣椒', '小米辣']],
  ['meat', ['肉', '排骨', '鸡腿', '鸡翅', '鸡胸', '牛排', '五花', '里脊', '香肠', '培根']],
  ['cabbage', ['白菜', '青菜', '菠菜', '生菜', '油菜', '油麦菜', '包菜', '卷心菜', '娃娃菜', '空心菜']],
  ['rice', ['大米', '米饭', '糯米', '小米', '米']],
  ['tofu', ['豆腐', '油豆腐', '腐竹', '豆干', '千张']],
  ['salt', ['盐']],
  ['oil', ['油', '花生油']],
  ['potato', ['土豆', '马铃薯', '薯']],
  ['mushroom', ['菇', '蘑']],
  ['shrimp', ['虾', '蟹', '扇贝', '干贝', '贝类', '花甲', '蛤', '蛏', '蚝', '鱿鱼']],
  ['noodle', ['面', '粉丝', '粉条', '米粉', '米线', '河粉']],
  ['apple', ['苹果', '梨', '香蕉', '橙', '橘', '柚', '葡萄', '草莓', '西瓜', '芒果', '蓝莓', '猕猴桃', '水果']]
];
// Icon for an ingredient or dish name. The keyword that appears earliest in the name wins ("番茄炒蛋" → tomato,
// "鸡蛋" → egg); on a tie the longer keyword wins ("油菜" → cabbage, "米粉" → noodle, "酱油" → none). '' = no icon.
function iconFor(name) {
  const n = name || '';
  let best = ''; let at = Infinity; let len = 0;
  ICON_RULES.forEach((r) => r[1].forEach((k) => {
    const p = n.indexOf(k);
    if (p >= 0 && (p < at || (p === at && k.length > len))) { at = p; len = k.length; best = r[0]; }
  }));
  return best;
}
// Initial for the fallback letter tile; skip a size prefix so 大白菜 / 大米 do not both read "大".
function initialOf(name) {
  const n = name || '?';
  return n.length > 1 && /^[大小]/.test(n) ? n.charAt(1) : n.charAt(0);
}

// ---- meta option key → Chinese label (app.globalData.meta: allergen_options / avoid_options / goals / activity_levels …)
// metaLabel('avoid_options', 'spicy') → '辣'. Unknown keys return `fallback` (default: the key itself).
function metaLabel(kind, key, fallback) {
  const app = typeof getApp === 'function' ? getApp() : null;
  const meta = (app && app.globalData && app.globalData.meta) || {};
  const opt = (meta[kind] || []).find((o) => o.key === key);
  if (opt) return opt.label;
  return fallback === undefined ? key : fallback;
}
function metaLabels(kind, keys) {
  return (keys || []).map((k) => metaLabel(kind, k));
}

function money(v) {
  return (Math.round((v || 0) * 100) / 100).toFixed(2);
}

function pct(v) {
  return Math.round((v || 0) * 100);
}

function today() {
  const d = new Date();
  const m = ('0' + (d.getMonth() + 1)).slice(-2);
  const day = ('0' + d.getDate()).slice(-2);
  return d.getFullYear() + '-' + m + '-' + day;
}

function chooseImage(sourceType) {
  return new Promise((resolve, reject) => {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: sourceType || ['camera', 'album'],
      sizeType: ['compressed'],
      success: (res) => resolve(res.tempFiles[0].tempFilePath),
      fail: reject
    });
  });
}

module.exports = {
  MEAL, KIND, LEVEL_TAG, VARIANT, AGENT_ICON, ICON_RULES,
  money, pct, today, chooseImage, iconFor, initialOf, metaLabel, metaLabels
};
