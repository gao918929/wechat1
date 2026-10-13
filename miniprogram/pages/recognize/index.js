const api = require("../../utils/api");
Page({
  data: {
    kind: "inventory",
    titles: { inventory: "食材入库", receipt: "小票记账", meal: "餐后复盘" },
    catalog: [],
    text: "",
    draft: null,
    items: [],
    paid: "",
    actual: false,
    contextIndex: 0,
    contexts: ["在家吃", "外食 / 外卖"],
    deduct: false,
    busy: false,
  },
  onLoad(options) {
    this.setData({
      kind: ["inventory", "receipt", "meal"].includes(options.kind)
        ? options.kind
        : "inventory",
    });
  },
  onShow: api.guard(async function () {
    const s = await api.ready();
    if (s) this.setData({ catalog: s.catalog });
  }),
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  row(e) {
    const i = Number(e.currentTarget.dataset.index),
      key = e.currentTarget.dataset.key;
    this.setData({ ["items[" + i + "]." + key]: e.detail.value });
  },
  setDraft(draft) {
    this.setData({
      draft,
      items: draft.items.map((i) => ({
        ...i,
        foodIndex: Math.max(
          0,
          this.data.catalog.findIndex((f) => f.id === i.ingredient_id),
        ),
        matched: !!i.ingredient_id,
        grams: i.grams === null ? "" : String(i.grams),
        price: i.line_cents === null ? "" : api.money(i.line_cents),
        expires: api.today(2),
      })),
      paid: draft.paid_cents === null ? "" : api.money(draft.paid_cents),
      contextIndex: draft.context === "out" ? 1 : 0,
    });
  },
  photo: api.guard(async function () {
    const media = await new Promise((resolve, reject) =>
      wx.chooseMedia({
        count: 1,
        mediaType: ["image"],
        sourceType: ["album", "camera"],
        success: resolve,
        fail: reject,
      }),
    );
    this.setData({ busy: true });
    const draft = await new Promise((resolve, reject) =>
      wx.uploadFile({
        url: api.base() + "/api" + api.groupPath("/recognize"),
        filePath: media.tempFiles[0].tempFilePath,
        name: "image",
        formData: { kind: this.data.kind },
        header: { Authorization: "Bearer " + getApp().globalData.token },
        timeout: 200000,
        success: (r) => {
          try {
            const data = JSON.parse(r.data);
            if (r.statusCode >= 200 && r.statusCode < 300) resolve(data);
            else reject(new Error(data.detail || "识别失败"));
          } catch (e) {
            reject(e);
          }
        },
        fail: () => reject(new Error("图片上传失败")),
      }),
    );
    this.setDraft(draft);
  }),
  text: api.guard(async function () {
    this.setData({ busy: true });
    const draft = this.data.draft
      ? await api.request("/drafts/" + this.data.draft.id + "/refine", "POST", {
          text: this.data.text,
        })
      : await api.request(api.groupPath("/drafts/text"), "POST", {
          kind: this.data.kind,
          text: this.data.text,
        });
    this.setDraft(draft);
    this.setData({ text: "" });
  }),
  remove(e) {
    this.setData({
      items: this.data.items.filter(
        (_, i) => i !== Number(e.currentTarget.dataset.index),
      ),
    });
  },
  matched(e) {
    const i = Number(e.currentTarget.dataset.index);
    this.setData({
      ["items[" + i + "].foodIndex"]: Number(e.detail.value),
      ["items[" + i + "].matched"]: true,
    });
  },
  confirm: api.guard(async function () {
    this.setData({ busy: true });
    if (this.data.items.some((i) => !i.matched))
      throw new Error("请手动匹配所有未知食材，或删除无法确认的条目");
    const items = this.data.items.map((i) => ({
      ingredient_id: this.data.catalog[Number(i.foodIndex)].id,
      grams: Number(i.grams),
      estimated: !!i.estimated,
      expires_on: i.expires,
    }));
    const draft = this.data.draft;
    if (this.data.kind === "inventory") {
      await api.request("/drafts/" + draft.id + "/confirm-inventory", "POST", {
        items: items.map((i, n) => ({
          ...i,
          freshness: this.data.items[n].freshness || "unknown",
        })),
      });
    } else if (this.data.kind === "receipt") {
      if (!this.data.actual || this.data.paid === "")
        throw new Error("请填写并确认实际支付金额");
      await api.request(api.groupPath("/receipts"), "POST", {
        request_id: "draft-" + draft.id,
        draft_id: draft.id,
        paid_cents: Math.round(Number(this.data.paid) * 100),
        actual_payment_confirmed: true,
        purchased_on: draft.purchased_on || api.today(),
        items: items.map((i, n) => ({
          ...i,
          line_cents:
            this.data.items[n].price === ""
              ? null
              : Math.round(Number(this.data.items[n].price) * 100),
        })),
      });
    } else {
      const consumption = [];
      if (Number(this.data.contextIndex) === 0 && this.data.deduct) {
        const stock = await api.request(api.groupPath("/inventory"));
        stock.sort((a, b) => a.expires_on.localeCompare(b.expires_on));
        for (const portion of items) {
          let left = portion.grams;
          for (const lot of stock) {
            if (
              lot.ingredient_id !== portion.ingredient_id ||
              ["expired", "not_fresh"].includes(lot.alert)
            )
              continue;
            const grams = Math.min(left, lot.grams);
            if (grams > 0) {
              consumption.push({ inventory_id: lot.id, grams });
              left -= grams;
              lot.grams -= grams;
            }
          }
          if (left > 0)
            throw new Error(
              "库存不足，请先修正入库重量，或关闭扣库存后仅记录营养",
            );
        }
      }
      await api.request(api.groupPath("/meals"), "POST", {
        request_id: "draft-" + draft.id,
        draft_id: draft.id,
        context: Number(this.data.contextIndex) ? "out" : "home",
        items: items.map((i) => ({
          ingredient_id: i.ingredient_id,
          grams: i.grams,
        })),
        consumption,
        estimated: items.some((i) => i.estimated),
      });
    }
    wx.showToast({ title: "已确认保存" });
    this.setData({ draft: null, items: [], actual: false });
    setTimeout(() => wx.navigateBack(), 700);
  }),
});
