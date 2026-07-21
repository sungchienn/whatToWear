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
  "未知": "#d7d1c7",
};

const UNKNOWN_VALUE = "未知";
const MIN_GUESS_FIELDS = 2;

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

function actualOptions(dim) {
  const options = [...(dim.options || [])];
  if (!options.includes(UNKNOWN_VALUE)) options.push(UNKNOWN_VALUE);
  return options;
}

function optionWeight(dim, option) {
  const weights = dim.option_weights || {};
  if (typeof weights[option] === "number") return weights[option];
  return 1 / Math.max(1, (dim.options || []).length);
}

function optionLine(dim, option) {
  return `${option} | ${(optionWeight(dim, option) * 100).toFixed(1)}`;
}

function parseOptionLine(line) {
  const [labelPart, probabilityPart] = line.split("|");
  const label = (labelPart || "").trim();
  const probability = Number((probabilityPart || "").trim()) / 100;
  return probability > 0 ? { label, probability } : { label };
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

function percentText(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function oddsTextFromProbability(value) {
  const probability = Math.max(0.001, Number(value || 0));
  return `${Math.min(50, 1 / probability).toFixed(2)}x`;
}

function dateTimeInputValue(seconds) {
  const date = seconds ? new Date(seconds * 1000) : new Date();
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function defaultObservedAtValue() {
  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return `${state.selectedDate || new Date().toISOString().slice(0, 10)}T${time}`;
}

function observedAtTimestamp() {
  const value = $("#actualObservedAt").value;
  const timestamp = value ? Math.floor(new Date(value).getTime() / 1000) : Math.floor(Date.now() / 1000);
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : Math.floor(Date.now() / 1000);
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
  if (data.is_reopened) $("#lockText").textContent = "已开放下注";
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
  renderAiOdds();
  renderHistory();
  renderLeaderboard();
  renderSettlements();
  renderSettlementPreview();
  renderBars();
  renderDimensionEditor();
  renderAiSettings();
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
    const options = actualOptions(dim);
    const selected = actualFields[dim.key] || options[0];
    return `
      <label class="actual-field">
        ${escapeHtml(dim.name)}
        <select class="actual-select" data-key="${escapeHtml(dim.key)}">${optionHtml(options, selected)}</select>
      </label>
    `;
  }).join("");
  $("#actualObservedAt").value = state.data.actual?.observed_at ? dateTimeInputValue(state.data.actual.observed_at) : defaultObservedAtValue();
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
      <small>池子 ${item.pool_size}，概率 ${percentText(item.probability)}</small>
      <small>初始 ${percentText(item.prior_probability)}${Number(item.ai_blend_weight || 0) > 0 ? `，AI ${percentText(item.ai_prior_probability)}` : ""}</small>
      <span>${Number(item.odds_weight).toFixed(2)}x</span>
    </div>
  `).join("");
}

function renderAiOdds() {
  const weights = state.data.ai_option_weights || {};
  const hasWeights = Object.values(weights).some((group) => group && Object.keys(group).length);
  const updatedAt = state.data.ai_option_weights_updated_at;
  const config = state.data.ai_config || {};
  $("#aiPredictionMeta").textContent = hasWeights
    ? `${updatedAt ? formatTs(updatedAt) : "已生成"} · ${config.weather_location || "未设地区"} · AI占比 ${Math.round(Number(config.ai_weight || 0) * 100)}%`
    : "暂无 AI 结果";
  $("#aiOddsByDimension").innerHTML = hasWeights
    ? activeDimensions().map((dim) => {
      const dimWeights = weights[dim.key] || {};
      const options = (dim.options || []).filter((option) => typeof dimWeights[option] === "number");
      if (!options.length) return "";
      return `
        <div class="ai-dimension">
          <strong>${escapeHtml(dim.name)}</strong>
          <div class="ai-option-grid">
            ${options.map((option) => `
              <div class="ai-option">
                <span>${escapeHtml(option)}</span>
                <small>概率 ${percentText(dimWeights[option])}</small>
                <b>${oddsTextFromProbability(dimWeights[option])}</b>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }).join("") || `<p class="muted">AI 尚未返回可展示的选项概率。</p>`
    : `<p class="muted">管理员启用 AI 并点击“调用 AI 更新赔率”后，所有成员都能在这里看到 AI 对每个选项的预测概率和对应赔率。</p>`;
}

function renderHistory() {
  const outfits = state.data.outfits;
  const isAdmin = Boolean(state.data.user?.is_admin);
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
          ${item.observed_at ? `<small>记录时间 ${formatTs(item.observed_at)}</small>` : ""}
          ${item.notes ? `<small>${escapeHtml(item.notes)}</small>` : ""}
        </div>
        ${isAdmin ? `<button class="secondary-action delete-outfit" data-date="${escapeHtml(item.date)}" type="button">删除并开放下注</button>` : ""}
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

function renderSettlementPreview() {
  const preview = state.data.settlement_preview || {};
  const entries = preview.entries || [];
  const canSettle = Boolean(preview.can_settle && !preview.settled);
  $("#settleBtn").disabled = !canSettle;
  $("#settleBtn").textContent = preview.settled ? "已结算" : "确认结算";
  $("#settlementSummary").innerHTML = `
    <div>
      <span>状态</span>
      <strong>${escapeHtml(preview.message || "暂无结算数据。")}</strong>
    </div>
    <div>
      <span>结算池</span>
      <strong>${Number(preview.pool || 0).toFixed(2)}</strong>
    </div>
    <div>
      <span>赢家赔率权重</span>
      <strong>${Number(preview.winner_weight || 0).toFixed(2)}</strong>
    </div>
  `;
  $("#settlementPreviewList").innerHTML = entries.length
    ? entries.map((item) => `
      <div class="list-item settlement-row ${item.result}">
        <div>
          <strong>${escapeHtml(item.name)} · ${labelResult(item.result)}</strong>
          <div class="pill-row">
            ${(item.labels || []).map((label) => `<span class="pill">${escapeHtml(label.name)}: ${escapeHtml(label.value)}</span>`).join("")}
            ${item.odds_weight ? `<span class="pill hot">${Number(item.odds_weight).toFixed(2)} 倍</span>` : ""}
          </div>
          ${typeof item.balance_before === "number" ? `<small>余额 ${Number(item.balance_before).toFixed(2)} -> ${Number(item.balance_after).toFixed(2)}</small>` : `<small>余额 ${Number(item.balance_after || 0).toFixed(2)}</small>`}
        </div>
        <strong>${Number(item.delta || 0).toFixed(2)}</strong>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>暂无结算明细</strong><small>需要先有竞猜和实际着装记录。</small></div></div>`;

  const transfers = preview.transfers || [];
  $("#transferList").innerHTML = transfers.length
    ? transfers.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.from)} -> ${escapeHtml(item.to)}</strong>
          <small>兑现 ${Number(item.amount).toFixed(2)} 份奶茶积分</small>
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>暂无转账建议</strong><small>作废或尚未形成输赢时不会产生兑现关系。</small></div></div>`;
}

function labelResult(result) {
  return {
    hit: "猜中",
    hit_all_right: "全员猜中再分配",
    miss: "猜错",
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
    if (Object.keys(fields).length < MIN_GUESS_FIELDS) {
      $("#guessOdds").textContent = "--";
      $("#guessProb").textContent = `至少选 ${MIN_GUESS_FIELDS} 个维度`;
      $("#poolInfo").textContent = "";
      return;
    }
    try {
      const result = await api("/api/odds-preview", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate, fields }),
      });
      $("#guessOdds").textContent = `${Number(result.odds_weight).toFixed(2)}x`;
      $("#guessProb").textContent = `预测概率 ${percentText(result.probability)}`;
      $("#poolInfo").textContent = Number(result.ai_blend_weight || 0) > 0
        ? `人工权重 ${Math.round(result.manual_blend_weight * 100)}%，AI ${Math.round(result.ai_blend_weight * 100)}%，历史 ${Math.round(result.history_blend_weight * 100)}%，混合 ${percentText(result.prior_probability)}`
        : `人工权重 ${Math.round(result.manual_blend_weight * 100)}%，历史 ${Math.round(result.history_blend_weight * 100)}%，概率 ${percentText(result.prior_probability)}，样本 ${result.sample_weight}`;
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
          选项与初始可能性，每行一个，格式：选项 | 百分比
          <textarea class="dimension-options">${escapeHtml((dim.options || []).map((option) => optionLine(dim, option)).join("\n"))}</textarea>
        </label>
      </div>
    </div>
  `).join("");
}

function renderAiSettings() {
  const config = state.data.ai_config || {};
  $("#aiEnabled").checked = Boolean(config.enabled);
  $("#manualWeightInput").value = Math.round(Number(config.manual_weight ?? 0.4) * 100);
  $("#aiWeightInput").value = Math.round(Number(config.ai_weight || 0) * 100);
  $("#historyWeightInput").value = Math.round(Number(config.history_weight ?? 0.2) * 100);
  $("#aiModelInput").value = config.model || "";
  $("#aiEndpointInput").value = config.endpoint || "";
  const knownLocations = Array.from($("#weatherLocationInput").options).map((option) => option.value);
  const location = config.weather_location || "上海";
  $("#weatherLocationInput").value = knownLocations.includes(location) ? location : "自定义";
  $("#customWeatherLocationInput").value = knownLocations.includes(location) ? "" : location;
  $("#aiWeatherInput").value = config.weather || "";
  $("#aiKeyInput").placeholder = config.has_api_key ? "已保存，留空不修改" : "请输入 API Key";
}

function collectDimensionsFromEditor() {
  return $$(".dimension-row").map((row, index) => ({
    key: row.querySelector(".dimension-key").value.trim(),
    name: row.querySelector(".dimension-name").value.trim(),
    active: row.querySelector(".dimension-active").checked,
    visual_part: row.querySelector(".dimension-part").value.trim(),
    order: Number(row.querySelector(".dimension-order").value || index),
    options: row.querySelector(".dimension-options").value.split("\n").map((item) => parseOptionLine(item.trim())).filter((item) => item.label),
  }));
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
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
      const fields = collectGuessFields();
      if (Object.keys(fields).length < MIN_GUESS_FIELDS) {
        toast(`至少选择 ${MIN_GUESS_FIELDS} 个竞猜维度`);
        return;
      }
      await api("/api/guesses", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate, fields }),
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
          observed_at: observedAtTimestamp(),
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

  $("#aiSettingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const apiKey = $("#aiKeyInput").value.trim();
      const selectedLocation = $("#weatherLocationInput").value;
      const aiConfig = {
        enabled: $("#aiEnabled").checked,
        manual_weight: Number($("#manualWeightInput").value || 0) / 100,
        ai_weight: Number($("#aiWeightInput").value || 0) / 100,
        history_weight: Number($("#historyWeightInput").value || 0) / 100,
        model: $("#aiModelInput").value.trim(),
        endpoint: $("#aiEndpointInput").value.trim(),
        weather_location: selectedLocation === "自定义" ? $("#customWeatherLocationInput").value.trim() : selectedLocation,
        weather: $("#aiWeatherInput").value.trim(),
      };
      if (apiKey) aiConfig.api_key = apiKey;
      await api("/api/ai/settings", {
        method: "POST",
        body: JSON.stringify({ ai_config: aiConfig }),
      });
      $("#aiKeyInput").value = "";
      toast("AI 设置已保存");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#refreshAiOddsBtn").addEventListener("click", async () => {
    try {
      toast("正在调用 AI 计算赔率");
      await api("/api/ai/odds/regenerate", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate }),
      });
      toast("AI 赔率已更新");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("#exportConfigBtn").addEventListener("click", async () => {
    try {
      const data = await api("/api/config/export");
      downloadJson(`what-to-wear-config-${state.selectedDate}.json`, data.config);
    } catch (err) {
      toast(err.message);
    }
  });

  $("#importConfigInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await readFileAsText(file);
      const config = JSON.parse(text);
      await api("/api/config/import", {
        method: "POST",
        body: JSON.stringify({ config }),
      });
      toast("配置已导入");
      await loadState();
    } catch (err) {
      toast(err.message);
    } finally {
      event.target.value = "";
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
    if (event.target.matches(".delete-outfit")) {
      const date = event.target.dataset.date;
      if (!window.confirm(`删除 ${date} 的实际着装记录，并恢复为可下注状态？当天结算记录也会删除。`)) return;
      api("/api/outfits/delete", {
        method: "POST",
        body: JSON.stringify({ date }),
      }).then(async () => {
        toast("记录已删除，日期已开放下注");
        if (state.selectedDate === date) {
          await loadState();
        } else {
          await loadState();
        }
      }).catch((err) => toast(err.message));
    }
  });
}

bindEvents();
loadState();
