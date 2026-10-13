const MEAL = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' };
const KIND = { main: '主菜', veg: '素菜', soup: '汤', staple: '主食', one_pot: '一锅出', breakfast: '早餐' };
const LEVEL_TAG = { ok: '', near_expiry: 'warn', expired: 'danger', not_fresh: 'danger' };
const VARIANT = { balanced: '平衡', health: '健康优先', budget: '预算优先' };
const AGENT_ICON = { health: '🩺', inventory: '🧊', budget: '💰', iterative: '🔁' };

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

module.exports = { MEAL, KIND, LEVEL_TAG, VARIANT, AGENT_ICON, money, pct, today, chooseImage };
