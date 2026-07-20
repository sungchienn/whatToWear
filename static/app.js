const state = {
  authMode: "login",
  data: null,
  selectedDate: new Date().toISOString().slice(0, 10),
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

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

function optionHtml(items) {
  return items.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

function findOdds(color, style) {
  const match = state.data?.predictions?.find((item) => item.color === color && item.style === style);
  return match || { probability: 0.01, odds_weight: 20 };
}

async function loadState() {
  try {
    const data = await api(`/api/state?date=${encodeURIComponent(state.selectedDate)}`);
    state.data = data;
    render();
  } catch (err) {
    state.data = null;
    $("#loginView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
  }
}

function render() {
  const data = state.data;
  if (!data) {
    $("#loginView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
    return;
  }
  if (!data.user) {
    $("#loginView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
    return;
  }

  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  $("#datePicker").value = data.date;
  $("#deadlineText").textContent = data.deadline;
  $("#lockText").textContent = data.is_locked ? "已锁定" : "可提交";
  $("#guessCount").textContent = data.guesses.length;
  $("#userBadge").textContent = `${data.user.name}${data.user.is_admin ? " · 管理员" : ""}`;
  $("#actualBadge").textContent = data.actual ? `${data.actual.color} / ${data.actual.style}` : "未记录";

  fillSelect("#guessColor", data.colors);
  fillSelect("#guessStyle", data.styles);
  fillSelect("#actualColor", data.colors);
  fillSelect("#actualStyle", data.styles);
  fillSelect("#actualVibe", data.vibes);

  $$(".admin-only").forEach((node) => node.classList.toggle("hidden", !data.user.is_admin));
  $("#modelVersion").textContent = data.model.version;
  $("#modelSummary").textContent = data.model.summary;

  renderGuessList();
  renderOdds();
  renderHistory();
  renderLeaderboard();
  renderSettlements();
  renderBars();
  updateOddsPreview();
}

function fillSelect(selector, values) {
  const select = $(selector);
  if (!select.dataset.ready) {
    select.innerHTML = optionHtml(values);
    select.dataset.ready = "1";
  }
}

function renderGuessList() {
  const items = state.data.guesses;
  $("#guessList").innerHTML = items.length
    ? items.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.name)}</strong>
          <div class="pill-row">
            <span class="pill">${escapeHtml(item.color)} / ${escapeHtml(item.style)}</span>
            ${item.odds_weight ? `<span class="pill hot">${item.odds_weight.toFixed(2)} 倍</span>` : ""}
          </div>
          <small>${formatTs(item.submitted_at)}</small>
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>还没有人提交</strong><small>截止前可修改自己的竞猜。</small></div></div>`;
}

function renderOdds() {
  $("#topOdds").innerHTML = state.data.top_predictions.map((item) => `
    <div class="odds-card">
      <strong>${escapeHtml(item.color)} / ${escapeHtml(item.style)}</strong>
      <small>概率 ${(item.probability * 100).toFixed(1)}%</small>
      <span>${item.odds_weight.toFixed(2)}x</span>
    </div>
  `).join("");
}

function renderHistory() {
  const outfits = state.data.outfits;
  $("#historyCount").textContent = `${outfits.length} 条`;
  $("#historyList").innerHTML = outfits.length
    ? outfits.map((item) => `
      <div class="list-item">
        <div>
          <strong>${escapeHtml(item.date)} · ${escapeHtml(item.color)} / ${escapeHtml(item.style)}</strong>
          <div class="pill-row">
            <span class="pill">${escapeHtml(item.vibe || "其他")}</span>
            ${item.tags ? `<span class="pill">${escapeHtml(item.tags)}</span>` : ""}
          </div>
          ${item.notes ? `<small>${escapeHtml(item.notes)}</small>` : ""}
        </div>
      </div>
    `).join("")
    : `<div class="list-item"><div><strong>暂无历史记录</strong><small>管理员记录后会自动进入赔率模型。</small></div></div>`;
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
  renderBarSet("#colorBars", "颜色分布", state.data.analytics.color_counts);
  renderBarSet("#styleBars", "款式分布", state.data.analytics.style_counts);
}

function renderBarSet(selector, title, counts) {
  const entries = Object.entries(counts).filter(([, value]) => value > 0);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  $(selector).innerHTML = [`<strong>${title}</strong>`, ...entries.slice(0, 8).map(([name, count]) => `
    <div class="bar">
      <span>${escapeHtml(name)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(6, count / max * 100)}%"></div></div>
      <span>${count}</span>
    </div>
  `)].join("");
}

function updateOddsPreview() {
  if (!state.data) return;
  const color = $("#guessColor").value || state.data.colors[0];
  const style = $("#guessStyle").value || state.data.styles[0];
  const odds = findOdds(color, style);
  $("#guessOdds").textContent = `${Number(odds.odds_weight).toFixed(2)}x`;
  $("#guessProb").textContent = `预测概率 ${(Number(odds.probability) * 100).toFixed(1)}%`;
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
    const body = {
      name: $("#authName").value,
      pin: $("#authPin").value,
      invite_code: $("#authInvite").value,
    };
    try {
      await api(state.authMode === "register" ? "/api/register" : "/api/login", {
        method: "POST",
        body: JSON.stringify(body),
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

  $("#guessColor").addEventListener("change", updateOddsPreview);
  $("#guessStyle").addEventListener("change", updateOddsPreview);

  $("#guessForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/guesses", {
        method: "POST",
        body: JSON.stringify({
          date: state.selectedDate,
          color: $("#guessColor").value,
          style: $("#guessStyle").value,
        }),
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
          color: $("#actualColor").value,
          style: $("#actualStyle").value,
          vibe: $("#actualVibe").value,
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

  $("#regenOddsBtn").addEventListener("click", async () => {
    try {
      await api("/api/predictions/regenerate", {
        method: "POST",
        body: JSON.stringify({ date: state.selectedDate }),
      });
      toast("赔率已重算");
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });
}

bindEvents();
loadState();