const state = {
  authMode: "login",
  data: null,
  selectedDate: new Date().toISOString().slice(0, 10),
  oddsTimer: null,
  editorDimensions: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const COLOR_MAP = {
  "黑色": "#202124",
  "白色": "#f8f7f1",
  "灰色": "#8d9399",
  "蓝色": "#2563a8",
  "绿色": "#2d7d4f",
  "红色": "#b43d2f",
  "粉色": "#e8a0b8",
  "黄色": "#e6bd43",
  "卡其": "#c4a774",
  "棕色": "#7c5438",
  "紫色": "#7752a8",
  "透明外套": "rgba(135, 190, 210, .35)",
  "其他": "#9a9184",
  "不穿": "#f0c7ad",
  "下装失踪": "#f0c7ad",
};

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
    ...options,
  });
  if (res.status === 204) return {};
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function optionHtml(items, selected = "") {
  return items.map((item) => {
    const isSelected = item === selected ? "selected" : "";
    return `<option value="${escapeHtml(item)}" ${isSelected}>${escapeHtml(item)}</option>`;
  }).join("");
}

function formatTs(seconds) {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function activeDimensions() {
  return (state.data?.dimensions || []).filter((dim) => dim.active);
}

async function loadState() {
  try {
    const data = await api(`/api/state?date=${encodeURIComponent(state.selectedDate)}`);
    state.data = data;
    state.editorDimensions = JSON.parse(JSON.stringify(data.dimensions || []));
    render();
  } catch (err) {
    state.data = null;
    $("#loginView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
  }
}

function render() {
  const data = state.data;
  if (!data || !data.user) {
    $("#loginView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
    return;
  }

  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  $("#datePicker").value = data.date;
  $("#deadlineText").textContent = data.deadline;
  $("#deadlineInput").value = data.deadline;
  $("#lockText").textContent = data.is_locked ? "已锁定" : "可提交";
  $("#guessCount").textContent = data.guesses.length;
  $("#userBadge").textContent = `${data.user.name}${data.user.is_admin ? " · 管理员" : ""}`;
  $("#actualBadge").textContent = data.actual ? data.actual.summary : "未记录";
  $("#modelVersion").textContent = data.model.version;
  $("#modelSummary").textContent = data.model.summary;

  $$(".admin-only").forEach((node) => node.classList.toggle("hidden", !data.user.is_admin));

  renderGuessFields();
  renderActualFields();
  renderGuessList();
  renderRecommendations();
  renderHistory();
  renderLeaderboard();
  renderSettlements();
  renderBars();
  renderDimensionEditor();
  updatePreview();
  updateOddsPreview();
}

function renderGuessFields() {
  const existing = myGuessFields();
  $("#guessFields").innerHTML = activeDimensions().map((dim, index) => {
    const checked = existing[dim.key] || (Object.keys(existing).length === 0 && ["upper_color", "top_style"].includes(dim.key));
    const selected = existing[dim.key] || dim.options[0];
    return `
      <div class="field-card ${checked ? "enabled" : ""}" data-field-card="${escapeHtml(dim.key)}">
        <label class="field-toggle">
          <input type="checkbox" class="guess-enabled" data-key="${escapeHtml(dim.key)}" ${checked ? "checked" : ""} />
          <span>${escapeHtml(dim.name)}</span>
        </label>
        <select class="guess-select" data-key="${escapeHtml(dim.key)}">${optionHtml(dim.options, selected)}</select>
      </div>
    `;
  }).join("");
}

function renderActualFields() {
  const actualFields = state.data.actual?.fields || {};
  $("#actualFields").innerHTML = activeDimensions().map((dim) => {
    const selected = actualFields[dim.key] || dim.options[0];
    return `
      <label class="actual-field">
        ${escapeHtml(dim.name)}
        <select class="actual-select" data-key="${escapeHtml(dim.key)}">${optionHtml(dim.options, selected)}</select>
      </label>
    `;
  }).join("");
  $("#actualTags").value = state.data.actual?.tags || "";
  $("#actualNotes").value = state.data.actual?.notes || "";
}

function myGuessFields() {
  const userId = state.data?.user?.id;
  return state.data?.guesses?.find((guess) => guess.user_id === userId)?.fields || {};
}

function collectGuessFields() {
  const fields = {};
  $$(".guess-enabled").forEach((checkbox) => {
    const key = checkbox.dataset.key;
    const card = checkbox.closest(".field-card");
    card.classList.toggle("enabled", checkbox.checked);
    if (checkbox.checked) {
      fields[key] = card.querySelector(".guess-select").value;
    }
  });
  return fields;
}

function collectActualFields() {
  const fields = {};
  $$(".actual-select").forEach((select) => {
    fields[select.dataset.key] = select.value;
  });
  return fields;
}

function renderGuessList() {
  const items = state.data.guesses;
  $("#guessList").innerHTML = items.length
    ? items.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.name)}</strong>
          <div class="pill-row">
            ${item.labels.length ? item.labels.map((label) => `<span class="pill">${escapeHtml(label.name)}: ${escapeHtml(label.value)}</span>`).join("") : `<span class="pill">${escapeHtml(item.summary)}</span>`}
            ${item.odds_weight ? `<span class="pill hot">${Number(item.odds_weight).toFixed(2)} 倍</span>` : ""}
          </div>
          <small>${formatTs(item.submitted_at)}</small>
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>还没有人提交</strong><small>截止前可修改自己的竞猜。</small></div></div>`;
}

function renderRecommendations() {
  const items = state.data.recommendations || [];
  $("#topOdds").innerHTML = items.map((item) => `
    <div class="odds-card">
      <strong>${escapeHtml(item.labels.map((label) => label.value).join(" / "))}</strong>
      <small>池子 ${item.pool_size}，概率 ${(item.probability * 100).toFixed(1)}%</small>
      <span>${Number(item.odds_weight).toFixed(2)}x</span>
    </div>
  `).join("");
}

function renderHistory() {
  const outfits = state.data.outfits;
  $("#historyCount").textContent = `${outfits.length} 条`;
  $("#historyCount2").textContent = `${outfits.length} 条`;
  $("#historyList").innerHTML = outfits.length
    ? outfits.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.date)}</strong>
          <div class="pill-row">
            ${item.labels.slice(0, 8).map((label) => `<span class="pill">${escapeHtml(label.name)}: ${escapeHtml(label.value)}</span>`).join("")}
          </div>
          ${item.notes ? `<small>${escapeHtml(item.notes)}</small>` : ""}
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>暂无历史记录</strong><small>管理员记录后会进入赔率模型。</small></div></div>`;
}

function renderLeaderboard() {
  $("#leaderboard").innerHTML = state.data.users.map((user, index) => `
    <div class="list-item">
      <div>
        <strong>${index + 1}. ${escapeHtml(user.name)}</strong>
        <small>${user.is_admin ? "管理员" : "成员"}</small>
      </div>
      <strong>${Number(user.balance).toFixed(2)}</strong>
    </div>
  `).join("");
}

function renderSettlements() {
  $("#settlementList").innerHTML = state.data.settlements.length
    ? state.data.settlements.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.date)} · ${escapeHtml(item.name)} · ${labelResult(item.result)}</strong>
          <small>变动 ${Number(item.delta).toFixed(2)}，余额 ${Number(item.balance_after).toFixed(2)}</small>
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>暂无结算</strong><small>记录实际着装后可结算。</small></div></div>`;
}

function labelResult(result) {
  return {
    hit: "猜中",
    miss: "猜错",
    void_all_right: "全员猜中作废",
    void_all_wrong: "全员猜错作废",
  }[result] || result;
}

function renderBars() {
  const groups = state.data.analytics.dimension_counts || [];
  $("#dimensionBars").innerHTML = groups.map((group) => {
    const entries = Object.entries(group.counts).filter(([, value]) => value > 0);
    const max = Math.max(1, ...entries.map(([, value]) => value));
    return `
      <div class="bar-group">
        <strong>${escapeHtml(group.name)}</strong>
        ${entries.slice(0, 8).map(([name, count]) => `
          <div class="bar">
            <span>${escapeHtml(name)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${Math.max(6, count / max * 100)}%"></div></div>
            <span>${count}</span>
          </div>
        `).join("")}
      </div>
    `;
  }).join("") || `<p class="muted">暂无历史分布。</p>`;
}

function updateOddsPreview() {
  clearTimeout(state.oddsTimer);
  state.oddsTimer = setTimeout(async () => {
    const fields = collectGuessFields();
    updatePreview(fields);
    if (Object.keys(fields).length === 0) {
      $("#guessOdds").textContent = "--";
      $("#guessProb").textContent = "至少选一个维度";
      $("#poolInfo").textContent = "";
      return;
    }
    try {
      const result = await api("/api/odds-preview", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate, fields }),
      });
      $("#guessOdds").textContent = `${Number(result.odds_weight).toFixed(2)}x`;
      $("#guessProb").textContent = `预测概率 ${(Number(result.probability) * 100).toFixed(1)}%`;
      $("#poolInfo").textContent = `竞猜池 ${result.pool_size} 种，历史样本权重 ${result.sample_weight}`;
    } catch (err) {
      $("#guessOdds").textContent = "--";
      $("#guessProb").textContent = err.message;
      $("#poolInfo").textContent = "";
    }
  }, 180);
}

function cssColor(value, fallback) {
  return COLOR_MAP[value] || fallback;
}

function updatePreview(providedFields) {
  const fields = providedFields || collectGuessFields();
  $("#avatarUpper").style.background = cssColor(fields.upper_color, "#d8d4ca");
  $("#avatarLower").style.background = cssColor(fields.lower_color, "#8d9399");
  $("#avatarShoes").style.background = cssColor(fields.shoes_color, "#333");
  $("#avatarOuter").style.background = fields.outerwear && fields.outerwear !== "无外套"
    ? cssColor(fields.outerwear_color || fields.upper_color, "rgba(22, 108, 104, .28)")
    : "transparent";
  $("#avatarOuter").classList.toggle("visible", Boolean(fields.outerwear && fields.outerwear !== "无外套"));
  $("#avatarLegwear").style.background = fields.legwear && fields.legwear.includes("丝") ? "rgba(40, 40, 45, .34)" : "transparent";
  $("#avatarHair").className = `avatar-hair hair-${hairClass(fields.hair_style)}`;
  $("#upperLabel").textContent = fields.top_style || "上身";
  $("#lowerLabel").textContent = fields.lower_style || "下身";
  $("#previewCaption").textContent = Object.values(fields).join(" / ") || "选择维度后会实时变化";
}

function hairClass(value = "") {
  if (value.includes("长")) return "long";
  if (value.includes("马尾")) return "tail";
  if (value.includes("丸子")) return "bun";
  if (value.includes("帽子")) return "cap";
  return "short";
}

function renderDimensionEditor() {
  $("#dimensionEditor").innerHTML = state.editorDimensions.map((dim, index) => `
    <div class="dimension-row" data-dim-index="${index}">
      <div class="dimension-head">
        <label class="inline-check">
          <input type="checkbox" class="dimension-active" ${dim.active ? "checked" : ""} />
          启用
        </label>
        <button class="secondary-action remove-dimension" type="button">删除</button>
      </div>
      <div class="form-grid">
        <label>
          字段 key
          <input class="dimension-key" value="${escapeHtml(dim.key)}" />
        </label>
        <label>
          显示名称
          <input class="dimension-name" value="${escapeHtml(dim.name)}" />
        </label>
        <label>
          视觉部位
          <input class="dimension-part" value="${escapeHtml(dim.visual_part || dim.key)}" />
        </label>
        <label>
          排序
          <input class="dimension-order" type="number" value="${Number(dim.order || index)}" />
        </label>
        <label class="wide">
          选项，每行一个
          <textarea class="dimension-options">${escapeHtml((dim.options || []).join("\n"))}</textarea>
        </label>
      </div>
    </div>
  `).join("");
}

function collectDimensionsFromEditor() {
  return $$(".dimension-row").map((row, index) => ({
    key: row.querySelector(".dimension-key").value.trim(),
    name: row.querySelector(".dimension-name").value.trim(),
    active: row.querySelector(".dimension-active").checked,
    visual_part: row.querySelector(".dimension-part").value.trim(),
    order: Number(row.querySelector(".dimension-order").value || index),
    options: row.querySelector(".dimension-options").value.split("\n").map((item) => item.trim()).filter(Boolean),
  }));
}

function bindEvents() {
  $$(".segment").forEach((button) => {
    button.addEventListener("click", () => {
      state.authMode = button.dataset.authMode;
      $$(".segment").forEach((node) => node.classList.toggle("active", node === button));
      $("#inviteRow").classList.toggle("hidden", state.authMode !== "register");
    });
  });

  $("#authForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(state.authMode === "register" ? "/api/register" : "/api/login", {
        method: "POST",
        body: JSON.stringify({
          name: $("#authName").value,
          pin: $("#authPin").value,
          invite_code: $("#authInvite").value,
        }),
      });
      toast("已登录");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#logoutBtn").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    state.data = null;
    render();
  });

  $("#datePicker").addEventListener("change", async (event) => {
    state.selectedDate = event.target.value;
    await loadState();
  });

  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab").forEach((node) => node.classList.toggle("active", node === button));
      $$(".tab-panel").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.panel !== button.dataset.tab));
    });
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches(".guess-enabled, .guess-select")) {
      updateOddsPreview();
    }
  });

  $("#guessForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/guesses", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate, fields: collectGuessFields() }),
      });
      toast("竞猜已保存");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#outfitForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/outfits", {
        method: "POST",
        body: JSON.stringify({
          date: state.selectedDate,
          fields: collectActualFields(),
          tags: $("#actualTags").value,
          notes: $("#actualNotes").value,
        }),
      });
      toast("实际着装已保存");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#settleBtn").addEventListener("click", async () => {
    try {
      const data = await api("/api/settle", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate }),
      });
      toast(`已结算 ${data.entries} 条`);
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ deadline: $("#deadlineInput").value }),
      });
      toast("设置已保存");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#dimensionForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/dimensions", {
        method: "POST",
        body: JSON.stringify({ dimensions: collectDimensionsFromEditor() }),
      });
      toast("维度配置已保存");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#addDimensionBtn").addEventListener("click", () => {
    state.editorDimensions.push({
      key: `custom_${Date.now()}`,
      name: "新维度",
      active: true,
      visual_part: "custom",
      order: state.editorDimensions.length,
      options: ["选项A", "选项B"],
    });
    renderDimensionEditor();
  });

  document.addEventListener("click", (event) => {
    if (event.target.matches(".remove-dimension")) {
      const row = event.target.closest(".dimension-row");
      state.editorDimensions.splice(Number(row.dataset.dimIndex), 1);
      renderDimensionEditor();
    }
  });
}

bindEvents();
loadState();
