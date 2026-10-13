(() => {
  const $ = (s) => document.querySelector(s),
    $$ = (s) => [...document.querySelectorAll(s)];
  const esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const money = (c) => (Number(c || 0) / 100).toFixed(2),
    today = () =>
      new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 10);
  let token = localStorage.getItem("mealagent_token") || "",
    group = localStorage.getItem("mealagent_group") || "",
    foods = [],
    members = [],
    job = null,
    draft = null,
    poll = null,
    variant = 0;
  function notice(text) {
    $("#toast").textContent = text;
    $("#toast").hidden = false;
    setTimeout(() => ($("#toast").hidden = true), 12000);
  }
  async function api(path, method = "GET", body) {
    const headers = { Authorization: "Bearer " + token };
    if (!(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    const r = await fetch("/api" + path, {
      method,
      headers,
      body:
        body === undefined
          ? undefined
          : body instanceof FormData
            ? body
            : JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) {
      if (r.status === 401) {
        token = "";
        localStorage.removeItem("mealagent_token");
        $("#auth").hidden = false;
      }
      throw new Error(
        typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail),
      );
    }
    return d;
  }
  const gp = (path) => {
    if (!group) throw new Error("请先创建或加入群组");
    return "/groups/" + group + path;
  };
  const id = () => crypto.randomUUID();
  function safe(fn) {
    return async (e) => {
      e?.preventDefault();
      const button = e?.submitter || e?.currentTarget;
      if (button?.tagName === "BUTTON") button.disabled = true;
      try {
        await fn(e);
      } catch (err) {
        notice(err.message);
      } finally {
        if (button?.tagName === "BUTTON") button.disabled = false;
      }
    };
  }
  function form(id, fn) {
    $(id).addEventListener(
      "submit",
      safe((e) => fn(new FormData(e.target), e)),
    );
  }
  function tab(name) {
    $$(".tab").forEach((s) => (s.hidden = s.id !== name));
    $$("nav button").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === name),
    );
  }
  $$("[data-tab]").forEach((b) => (b.onclick = () => tab(b.dataset.tab)));
  $$("[data-goto]").forEach((b) => (b.onclick = () => tab(b.dataset.goto)));
  $("#groupPicker").onchange = safe(async (e) => {
    group = e.target.value;
    localStorage.setItem("mealagent_group", group);
    await refresh();
  });
  form("#loginForm", async (f) => {
    const r = await api("/auth/dev", "POST", Object.fromEntries(f));
    token = r.token;
    localStorage.setItem("mealagent_token", token);
    $("#loginForm").reset();
    await refresh();
  });
  $("#logout").onclick = safe(async () => {
    await api("/auth/logout", "POST", {});
    token = "";
    localStorage.removeItem("mealagent_token");
    location.reload();
  });
  form("#createGroup", async (f) => {
    const r = await api("/groups", "POST", { name: f.get("name") });
    group = r.id;
    localStorage.setItem("mealagent_group", group);
    $("#invite").textContent = "一次性展示的邀请码：" + r.invite_code;
    await refresh();
  });
  form("#joinGroup", async (f) => {
    const r = await api("/groups/join", "POST", { code: f.get("code") });
    group = r.id;
    localStorage.setItem("mealagent_group", group);
    await refresh();
  });
  form("#stockForm", async (f) => {
    await api(gp("/inventory"), "POST", {
      ingredient_id: f.get("ingredient_id"),
      grams: Number(f.get("grams")),
      expires_on: f.get("expires_on"),
      estimated: f.has("estimated"),
    });
    notice("食材已入库");
    await refresh();
  });
  form("#priceForm", async (f) => {
    await api(gp("/prices"), "POST", {
      ingredient_id: f.get("ingredient_id"),
      cents_per_kg: Math.round(Number(f.get("price")) * 100),
      source: f.get("source"),
    });
    notice("参考价格已保存，明确标记为估算");
  });
  form("#receiptForm", async (f) => {
    await api(gp("/receipts"), "POST", {
      request_id: id(),
      paid_cents: Math.round(Number(f.get("paid")) * 100),
      actual_payment_confirmed: true,
      items: [],
    });
    notice("实付账单已记录");
    await refresh();
  });
  form("#planForm", async (f) => {
    const body = {
      prompt: f.get("prompt"),
      days: Number(f.get("days")),
      start_date: f.get("start_date"),
      budget_mode: f.get("budget_mode"),
      budget_cents: Math.round(Number(f.get("budget")) * 100),
      diners: f.getAll("diners"),
      override_soft: f.has("override_soft"),
      request_id: id(),
    };
    job = await api(gp("/plans"), "POST", body);
    renderJob();
    watch(job.id);
  });
  $("#saveProfile").onclick = safe(async () => {
    await api("/me/profile", "PUT", JSON.parse($("#profileEditor").value));
    notice("画像已保存");
  });
  $("#viewTarget").onclick = safe(async () => {
    $("#targetOutput").textContent = JSON.stringify(
      await api("/me/target"),
      null,
      2,
    );
  });
  form("#feedbackForm", async (f, e) => {
    await api(gp("/feedback"), "POST", {
      action: "substitute",
      text: f.get("text"),
      shared: f.has("shared"),
    });
    e.target.reset();
    notice("已记录，下次规划将参考该反馈");
    await refresh();
  });
  form("#recognizeForm", async (f) => {
    const kind = f.get("kind"),
      image = f.get("image");
    notice("识别中，结果需你确认后才会生效…");
    if (image?.size) {
      const upload = new FormData();
      upload.set("kind", kind);
      upload.set("image", image);
      draft = await api(gp("/recognize"), "POST", upload);
    } else
      draft = await api(gp("/drafts/text"), "POST", {
        kind,
        text: f.get("text"),
      });
    renderDraft();
  });
  $("#refineDraft").onclick = safe(async () => {
    draft = await api("/drafts/" + draft.id + "/refine", "POST", {
      text: $("#refineText").value,
    });
    renderDraft();
  });
  $("#confirmDraft").onclick = safe(async () => {
    const body = JSON.parse($("#draftEditor").value);
    if (draft.kind === "inventory")
      await api("/drafts/" + draft.id + "/confirm-inventory", "POST", body);
    else
      await api(
        gp(draft.kind === "receipt" ? "/receipts" : "/meals"),
        "POST",
        body,
      );
    draft = null;
    $("#draftCard").hidden = true;
    notice("已确认保存");
    await refresh();
  });
  function renderDraft() {
    const items = draft.items.map((i) => ({
      ingredient_id: i.ingredient_id,
      grams: i.grams,
      estimated: i.estimated,
      expires_on: today(),
    }));
    let body = { items };
    if (draft.kind === "receipt")
      body = {
        request_id: "draft-" + draft.id,
        draft_id: draft.id,
        paid_cents: draft.paid_cents,
        actual_payment_confirmed: true,
        purchased_on: draft.purchased_on || today(),
        items: items.map((i, n) => ({
          ...i,
          line_cents: draft.items[n].line_cents,
        })),
      };
    if (draft.kind === "meal")
      body = {
        request_id: "draft-" + draft.id,
        draft_id: draft.id,
        context: draft.context === "out" ? "out" : "home",
        items: items.map((i) => ({
          ingredient_id: i.ingredient_id,
          grams: i.grams,
        })),
        consumption: [],
        estimated: true,
      };
    if (draft.kind === "inventory")
      body.items = body.items.map((i, n) => ({
        ...i,
        freshness: draft.items[n].freshness,
      }));
    $("#draftEditor").value = JSON.stringify(body, null, 2);
    $("#draftWarnings").textContent =
      "识别警告：" +
      JSON.stringify(draft.warnings) +
      "\n原始识别项：" +
      JSON.stringify(draft.items, null, 2);
    $("#draftCard").hidden = false;
  }
  function renderJob() {
    if (!job) return;
    const box = $("#jobStatus");
    box.hidden = false;
    box.innerHTML =
      '<span class="badge">' +
      esc(job.status) +
      "</span><h2>" +
      esc(job.message || "生成中") +
      "</h2><p>任务保存在后端。关闭页面不会取消；刷新后仍可查看。</p>" +
      (job.errors
        ? "<pre>" + esc(JSON.stringify(job.errors, null, 2)) + "</pre>"
        : "");
    if (job.result) renderVariants();
    else $("#planResults").innerHTML = "";
  }
  function renderVariants() {
    const variants = job.result.variants,
      v = variants[variant] || variants[0];
    $("#planResults").innerHTML =
      '<div class="variant-tabs">' +
      variants
        .map(
          (v, i) =>
            '<button data-variant="' +
            i +
            '" class="' +
            (i === variant ? "active" : "") +
            '">' +
            esc(
              v.mode === "balanced"
                ? "均衡优先"
                : v.mode === "health"
                  ? "健康优先"
                  : "预算优先",
            ) +
            "</button>",
        )
        .join("") +
      '</div><article class="card"><div class="row"><h2>' +
      esc(v.title) +
      "</h2><strong>采购 ¥" +
      money(v.cost_cents) +
      "</strong></div><p>" +
      v.tradeoffs.map(esc).join(" · ") +
      "</p><p>" +
      v.warnings.map(esc).join(" · ") +
      '</p><div class="actions"><button id="selectPlan">选用并共享</button><button id="copyShopping" class="secondary">复制采购清单</button></div></article>' +
      v.days
        .map(
          (day) =>
            '<article class="card"><span class="eyebrow">' +
            esc(day.date) +
            "</span>" +
            day.dishes
              .map(
                (d) =>
                  "<h3>" +
                  esc(d.name) +
                  "</h3>" +
                  (v.split_mode
                    ? '<span class="badge">适合：' +
                      esc(
                        d.suitable_for.length
                          ? d.suitable_for
                              .map(
                                (id) =>
                                  members.find((m) => m.id === id)?.name || id,
                              )
                              .join("、")
                          : "全员",
                      ) +
                      "</span>"
                    : "") +
                  '<p class="ingredients">' +
                  d.ingredients
                    .map(
                      (i) =>
                        esc(
                          foods.find((f) => f.id === i.ingredient_id)?.name ||
                            i.ingredient_id,
                        ) +
                        " " +
                        i.grams +
                        "g",
                    )
                    .join(" · ") +
                  "</p><ol>" +
                  d.steps.map((s) => "<li>" + esc(s) + "</li>").join("") +
                  "</ol>",
              )
              .join("") +
            "</article>",
        )
        .join("") +
      '<article class="card"><h2>只买缺少的食材</h2>' +
      v.shopping
        .map(
          (i) =>
            "<p>" +
            esc(i.name) +
            " " +
            i.grams +
            "g · ¥" +
            money(i.cents) +
            ' <span class="badge">' +
            (i.estimated ? "估算" : "历史实价") +
            "</span></p>",
        )
        .join("") +
      '<p class="hint">' +
      esc(v.disclaimer) +
      "</p></article>";
    $$("[data-variant]").forEach(
      (b) =>
        (b.onclick = () => {
          variant = Number(b.dataset.variant);
          renderVariants();
        }),
    );
    $("#selectPlan").onclick = safe(async () => {
      await api("/plans/" + job.id + "/select", "POST", { mode: v.mode });
      notice("已选用并同步给群组");
    });
    $("#copyShopping").onclick = safe(async () => {
      await navigator.clipboard.writeText(
        [
          v.title,
          ...v.shopping.map(
            (i) =>
              i.name +
              " " +
              i.grams +
              "g ¥" +
              money(i.cents) +
              (i.estimated ? " (估算)" : ""),
          ),
          "合计 ¥" + money(v.cost_cents),
        ].join("\n"),
      );
      notice("采购清单已复制");
    });
  }
  function watch(key) {
    if (poll) clearInterval(poll);
    poll = setInterval(async () => {
      try {
        job = await api("/plans/" + key);
        renderJob();
        if (!["queued", "running"].includes(job.status)) {
          clearInterval(poll);
          poll = null;
        }
      } catch (e) {
        clearInterval(poll);
        notice(e.message);
      }
    }, 2500);
  }
  async function refresh() {
    const health = await api("/health");
    $("#connection").textContent = health.ai_configured
      ? "后端已连接 · AI 已配置"
      : "后端已连接 · AI 待配置";
    $("#auth").hidden = !!token;
    if (!token) return;
    const [gs, me, cat, personal] = await Promise.all([
      api("/groups"),
      api("/me"),
      api("/catalog"),
      api("/twins/personal"),
    ]);
    foods = cat;
    $("#profileEditor").value = JSON.stringify(me.profile, null, 2);
    $("#personalTwin").textContent = JSON.stringify(personal, null, 2);
    group = gs.some((g) => g.id === group) ? group : gs[0]?.id || "";
    localStorage.setItem("mealagent_group", group);
    $("#groupPicker").innerHTML = gs.length
      ? gs
          .map(
            (g) =>
              '<option value="' +
              esc(g.id) +
              '"' +
              (g.id === group ? " selected" : "") +
              ">" +
              esc(g.name) +
              "</option>",
          )
          .join("")
      : "<option>创建一个家庭 / 宿舍</option>";
    $$(".foods").forEach((select) => {
      const previous = select.value;
      select.innerHTML = foods
        .map(
          (f) =>
            '<option value="' +
            esc(f.id) +
            '">' +
            esc(f.name) +
            " / " +
            esc(f.id) +
            "</option>",
        )
        .join("");
      if (foods.some((f) => f.id === previous)) select.value = previous;
    });
    if (!group) return;
    const [stock, report, receipts, ms, notes, jobs, shared] =
      await Promise.all([
        api(gp("/inventory")),
        api(gp("/reports")),
        api(gp("/receipts")),
        api(gp("/members")),
        api("/notifications"),
        api(gp("/plans")),
        api(gp("/selected-plans")),
      ]);
    members = ms;
    $("#stockCount").textContent = stock.length;
    $("#alertCount").textContent =
      stock.filter((s) => s.alert !== "normal").length + " 项需要优先关注";
    $("#spent").textContent = "¥" + money(report.paid_cents);
    $("#mealCount").textContent = report.meal_count;
    $("#diners").innerHTML = ms
      .map(
        (m) =>
          '<label class="check"><input type="checkbox" name="diners" value="' +
          esc(m.id) +
          '" checked>' +
          esc(m.name) +
          "</label>",
      )
      .join("");
    $("#notifications").innerHTML = notes.length
      ? notes
          .slice(0, 6)
          .map((n) => "<p>" + esc(n.text) + "</p>")
          .join("")
      : "还没有通知。";
    $("#receiptList").innerHTML = receipts.length
      ? receipts
          .map(
            (r) =>
              '<div class="row"><p>' +
              esc(r.purchased_on) +
              "</p><strong>¥" +
              money(r.paid_cents) +
              "</strong></div>",
          )
          .join("")
      : "暂无实付记录";
    $("#stockList").innerHTML = stock.length
      ? stock
          .map(
            (s) =>
              '<div class="stockrow row"><div><h3>' +
              esc(s.food.name) +
              ' <span class="badge ' +
              (s.alert !== "normal" ? "warn" : "") +
              '">' +
              esc(s.alert) +
              "</span></h3><small>" +
              s.grams +
              "g · 到期 " +
              esc(s.expires_on) +
              (s.estimated ? " · 重量估算" : "") +
              '</small></div><div class="actions"><button class="secondary" data-consume="' +
              s.id +
              '">记录消耗</button><button class="danger" data-discard="' +
              s.id +
              '" data-version="' +
              s.version +
              '">丢弃</button></div></div>',
          )
          .join("")
      : '<div class="card empty">还没有食材。先添加库存或通过照片识别。</div>';
    $$("[data-consume]").forEach(
      (b) =>
        (b.onclick = safe(async () => {
          const grams = prompt("实际消耗多少克？");
          if (grams === null) return;
          await api(gp("/consume"), "POST", {
            request_id: id(),
            items: [{ inventory_id: b.dataset.consume, grams: Number(grams) }],
          });
          await refresh();
        })),
    );
    $$("[data-discard]").forEach(
      (b) =>
        (b.onclick = safe(async () => {
          if (!confirm("确认丢弃？库存将归零，不计入摄入。")) return;
          await api(
            gp(
              "/inventory/" +
                b.dataset.discard +
                "?version=" +
                b.dataset.version,
            ),
            "DELETE",
          );
          await refresh();
        })),
    );
    const rows = Object.entries(report.days),
      max = Math.max(1, ...rows.map(([, n]) => n.kcal || 0));
    $("#chart").innerHTML = rows.length
      ? rows
          .map(
            ([d, n]) =>
              '<div class="chart-row"><div class="row"><span>' +
              esc(d) +
              "</span><span>" +
              Math.round(n.kcal || 0) +
              " kcal / 蛋白 " +
              Math.round(n.protein || 0) +
              'g</span></div><div class="bar" style="width:' +
              ((n.kcal || 0) / max) * 100 +
              '%"></div></div>',
          )
          .join("")
      : "记录一餐后，趋势会出现在这里。";
    $("#sharedPlans").innerHTML = shared.length
      ? shared
          .map(
            (s) =>
              "<details><summary>" +
              esc(s.plan.title) +
              " · " +
              esc(s.plan.days[0].date) +
              "</summary>" +
              s.plan.days
                .map(
                  (d) =>
                    "<h3>" +
                    esc(d.date) +
                    "</h3>" +
                    d.dishes
                      .map(
                        (dish) =>
                          "<strong>" +
                          esc(dish.name) +
                          "</strong><p>" +
                          dish.ingredients
                            .map(
                              (i) =>
                                esc(
                                  foods.find((f) => f.id === i.ingredient_id)
                                    ?.name || i.ingredient_id,
                                ) +
                                " " +
                                i.grams +
                                "g",
                            )
                            .join(" · ") +
                          "</p><ol>" +
                          dish.steps
                            .map((step) => "<li>" + esc(step) + "</li>")
                            .join("") +
                          "</ol>",
                      )
                      .join(""),
                )
                .join("") +
              "<p>采购 ¥" +
              money(s.plan.cost_cents) +
              '</p><p class="hint">' +
              esc(s.plan.disclaimer) +
              "</p></details>",
          )
          .join("")
      : "尚未选用方案";
    try {
      $("#groupTwin").textContent = JSON.stringify(
        await api(gp("/twin")),
        null,
        2,
      );
    } catch (e) {
      $("#groupTwin").textContent = e.message;
    }
    if (jobs.length) {
      job = jobs[0];
      renderJob();
      if (["queued", "running"].includes(job.status)) watch(job.id);
    }
  }
  $$("input[type=date]").forEach((e) => (e.value = today()));
  safe(refresh)();
})();
