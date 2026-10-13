const api = require("../../utils/api");
Page({
  data: {
    report: null,
    rows: [],
    receipts: [],
    period: 0,
    periods: ["近 7 天", "近 30 天"],
    collective: false,
  },
  onShow: api.guard(async function () {
    const s = await api.ready();
    if (s && s.group) await this.load();
  }),
  async load() {
    const days = this.data.period === 0 ? 7 : 30;
    const [r, receipts] = await Promise.all([
      api.request(
        api.groupPath(
          "/reports?days=" + days + "&collective=" + this.data.collective,
        ),
      ),
      api.request(api.groupPath("/receipts")),
    ]);
    const max = Math.max(1, ...Object.values(r.days).map((d) => d.kcal || 0));
    this.setData({
      report: {
        ...r,
        paid: api.money(r.paid_cents),
        budget: api.money(r.budget_cents),
        share: api.money(r.per_person_cents),
      },
      rows: Object.entries(r.days).map(([date, n]) => ({
        date,
        kcal: Math.round(n.kcal || 0),
        protein: Math.round(n.protein || 0),
        carbs: Math.round(n.carbs || 0),
        fat: Math.round(n.fat || 0),
        calcium:
          n.calcium_mg == null ? "未知" : Math.round(n.calcium_mg) + " mg",
        iron: n.iron_mg == null ? "未知" : Number(n.iron_mg).toFixed(2) + " mg",
        sodium: n.sodium_mg == null ? "未知" : Math.round(n.sodium_mg) + " mg",
        vitaminC:
          n.vitamin_c_mg == null ? "未知" : Math.round(n.vitamin_c_mg) + " mg",
        width: Math.round(((n.kcal || 0) * 100) / max),
      })),
      receipts: receipts.map((r) => ({ ...r, paid: api.money(r.paid_cents) })),
    });
  },
  change: api.guard(async function (e) {
    this.setData({
      [e.currentTarget.dataset.key]:
        e.currentTarget.dataset.key === "period"
          ? Number(e.detail.value)
          : e.detail.value,
    });
    await this.load();
  }),
  photo(e) {
    wx.navigateTo({
      url: "/pages/recognize/index?kind=" + e.currentTarget.dataset.kind,
    });
  },
  totalOnly: api.guard(async function () {
    const amount = await api.ask(
      "记一笔实付支出（元）",
      "仅金额，不会生成虚构的食材或价格",
    );
    if (amount === null) return;
    const yes = await new Promise((r) =>
      wx.showModal({
        title: "确认实际支付",
        content: "金额 ¥" + amount + "。账单不可修改，请确认后提交。",
        success: (x) => r(x.confirm),
      }),
    );
    if (!yes) return;
    await api.request(api.groupPath("/receipts"), "POST", {
      request_id: api.id(),
      paid_cents: Math.round(Number(amount) * 100),
      items: [],
      actual_payment_confirmed: true,
    });
    await this.load();
  }),
});
