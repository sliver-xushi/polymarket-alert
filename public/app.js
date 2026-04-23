const state = {
  markets: [],
  selectedMarketId: null,
  selectedIds: new Set(),
  simulation: null,
  loading: false,
  source: "loading",
  warning: null,
  tracker: null,
  manualCount: false,
};

const els = {
  sourceBadge: document.getElementById("sourceBadge"),
  liveSummary: document.getElementById("liveSummary"),
  refreshBtn: document.getElementById("refreshBtn"),
  marketCount: document.getElementById("marketCount"),
  marketNotice: document.getElementById("marketNotice"),
  marketUrlInput: document.getElementById("marketUrlInput"),
  resolveMarketBtn: document.getElementById("resolveMarketBtn"),
  marketList: document.getElementById("marketList"),
  periodLabel: document.getElementById("periodLabel"),
  marketTitle: document.getElementById("marketTitle"),
  volumeMetric: document.getElementById("volumeMetric"),
  liquidityMetric: document.getElementById("liquidityMetric"),
  remainingMetric: document.getElementById("remainingMetric"),
  countInput: document.getElementById("countInput"),
  budgetInput: document.getElementById("budgetInput"),
  bufferInput: document.getElementById("bufferInput"),
  strategyInput: document.getElementById("strategyInput"),
  trackerSourceMetric: document.getElementById("trackerSourceMetric"),
  projectionMetric: document.getElementById("projectionMetric"),
  riskMetric: document.getElementById("riskMetric"),
  basketCostMetric: document.getElementById("basketCostMetric"),
  coverMetric: document.getElementById("coverMetric"),
  edgeMetric: document.getElementById("edgeMetric"),
  selectedCount: document.getElementById("selectedCount"),
  outcomeRows: document.getElementById("outcomeRows"),
  simulationStatus: document.getElementById("simulationStatus"),
  settlementAdviceValue: document.getElementById("settlementAdviceValue"),
  limitAdviceValue: document.getElementById("limitAdviceValue"),
  swingAdviceValue: document.getElementById("swingAdviceValue"),
  sharesValue: document.getElementById("sharesValue"),
  costValue: document.getElementById("costValue"),
  profitValue: document.getElementById("profitValue"),
  lossValue: document.getElementById("lossValue"),
  evValue: document.getElementById("evValue"),
  targetExitValue: document.getElementById("targetExitValue"),
  targetEntryValue: document.getElementById("targetEntryValue"),
  swingValue: document.getElementById("swingValue"),
  paperBtn: document.getElementById("paperBtn"),
  draftBtn: document.getElementById("draftBtn"),
  reloadTradesBtn: document.getElementById("reloadTradesBtn"),
  paperTradeList: document.getElementById("paperTradeList"),
  toast: document.getElementById("toast"),
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function fmtPct(value, digits = 1) {
  if (!Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

function fmtMarketPct(value) {
  if (!Number.isFinite(value)) return "-";
  if (value >= 0 && value < 0.01) return "<1%";
  return fmtPct(value);
}

function fmtPrice(value) {
  const price = Number(value);
  if (value === null || value === undefined || !Number.isFinite(price)) return "-";
  return price.toFixed(3);
}

function fmtUsd(value) {
  if (!Number.isFinite(value)) return "-";
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtCompactUsd(value) {
  if (!Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return fmtUsd(value);
}

function fmtNum(value, digits = 0) {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function hoursRemaining(market) {
  const end = parseDate(market?.endTime);
  if (!end) return null;
  return (end.getTime() - Date.now()) / 36e5;
}

function elapsedProgress(market) {
  const start = parseDate(market?.startTime);
  const end = parseDate(market?.endTime);
  if (!start || !end || end <= start) return null;
  return clamp((Date.now() - start.getTime()) / (end.getTime() - start.getTime()), 0, 1);
}

function outcomeMidpoint(outcome) {
  if (Number.isFinite(outcome.lower) && Number.isFinite(outcome.upper)) {
    return (outcome.lower + outcome.upper) / 2;
  }
  if (Number.isFinite(outcome.lower)) return outcome.lower + 18;
  if (Number.isFinite(outcome.upper)) return outcome.upper - 18;
  return null;
}

function erf(x) {
  const sign = x >= 0 ? 1 : -1;
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const ax = Math.abs(x);
  const t = 1 / (1 + p * ax);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return sign * y;
}

function normalCdf(x, mean, sigma) {
  return 0.5 * (1 + erf((x - mean) / (sigma * Math.SQRT2)));
}

function intervalLikelihood(outcome, projected, sigma) {
  if (!Number.isFinite(projected) || !Number.isFinite(sigma) || sigma <= 0) return 1;
  const low = Number.isFinite(outcome.lower) ? outcome.lower : -Infinity;
  const high = Number.isFinite(outcome.upper) ? outcome.upper : Infinity;
  if (low === -Infinity && high === Infinity) return 1;
  if (low === -Infinity) return normalCdf(high, projected, sigma);
  if (high === Infinity) return 1 - normalCdf(low, projected, sigma);
  return Math.max(0, normalCdf(high, projected, sigma) - normalCdf(low, projected, sigma));
}

function selectedMarket() {
  return state.markets.find((market) => market.id === state.selectedMarketId) || state.markets[0] || null;
}

const MONTH_INDEX = {
  january: "01",
  february: "02",
  march: "03",
  april: "04",
  may: "05",
  june: "06",
  july: "07",
  august: "08",
  september: "09",
  october: "10",
  november: "11",
  december: "12",
};

function displayMarketTitle(market) {
  const title = market?.title || "";
  const range = title.match(/Elon Musk(?: musk)? # tweets ([A-Za-z]+) (\d{1,2}) - ([A-Za-z]+) (\d{1,2}), (\d{4})\?/i);
  if (range) {
    const [, startMonth, startDay, endMonth, endDay, year] = range;
    const start = `${year}/${MONTH_INDEX[startMonth.toLowerCase()]}/${String(Number(startDay)).padStart(2, "0")}`;
    const end = `${year}/${MONTH_INDEX[endMonth.toLowerCase()]}/${String(Number(endDay)).padStart(2, "0")}`;
    return `Elon Musk 发推次数预测（${start} - ${end}）`;
  }
  const monthly = title.match(/Elon Musk(?: musk)? # tweets in ([A-Za-z]+) (\d{4})\?/i);
  if (monthly) {
    const [, month, year] = monthly;
    return `Elon Musk 月度发推次数预测（${year}/${MONTH_INDEX[month.toLowerCase()] || month}）`;
  }
  return title || "等待市场数据";
}

function polymarketUrl(market) {
  if (market?.url) return market.url;
  if (market?.slug && !market.isSample) return `https://polymarket.com/event/${market.slug}`;
  return null;
}

function marketImpliedExpected(market) {
  let total = 0;
  let weighted = 0;
  for (const outcome of market.outcomes || []) {
    const mid = outcomeMidpoint(outcome);
    const price = Number(outcome.midPrice ?? outcome.gammaPrice ?? 0);
    if (Number.isFinite(mid) && price > 0) {
      total += price;
      weighted += price * mid;
    }
  }
  return total > 0 ? weighted / total : null;
}

function applyModel(market) {
  if (!market) return;
  const outcomes = market.outcomes || [];
  const buffer = Number(els.bufferInput.value || 0) / 100;
  const progress = elapsedProgress(market);
  const count = Number(els.countInput.value);
  const hasCount = Number.isFinite(count) && count >= 0 && Number.isFinite(progress) && progress > 0.025;
  const projected = hasCount ? count / progress : null;
  const widths = outcomes
    .map((outcome) => {
      if (Number.isFinite(outcome.lower) && Number.isFinite(outcome.upper)) {
        return Math.max(1, outcome.upper - outcome.lower + 1);
      }
      return null;
    })
    .filter(Number.isFinite);
  const width = widths.length ? widths.sort((a, b) => a - b)[Math.floor(widths.length / 2)] : 20;
  const sigma = hasCount ? Math.max(width * 1.1, (1 - progress) * 90 + width * 0.6) : null;

  const raw = outcomes.map((outcome) => clamp(Number(outcome.midPrice ?? outcome.gammaPrice ?? 0.01), 0.001, 0.999));
  const rawSum = raw.reduce((sum, value) => sum + value, 0) || 1;
  const scores = outcomes.map((outcome, index) => {
    const prior = raw[index] / rawSum;
    if (!hasCount) return prior;
    const likelihood = intervalLikelihood(outcome, projected, sigma);
    return prior * (0.25 + likelihood * 1.75);
  });
  const scoreSum = scores.reduce((sum, value) => sum + value, 0) || 1;

  outcomes.forEach((outcome, index) => {
    const probability = scores[index] / scoreSum;
    const entryPrice = Number(outcome.bestAsk ?? outcome.midPrice ?? outcome.gammaPrice ?? 0);
    const marketProb = marketProbability(outcome);
    outcome.modelProbability = probability;
    outcome.entryPrice = entryPrice;
    outcome.marketProbability = marketProb;
    outcome.limitTarget = clamp(probability - buffer, 0.001, 0.99);
    outcome.convergenceEdge = probability - (Number.isFinite(marketProb) ? marketProb : entryPrice);
    outcome.edge = probability - entryPrice - buffer;
  });
}

function projectionState(market) {
  const progress = elapsedProgress(market);
  const count = currentCount();
  if (!Number.isFinite(count) || count < 0 || !Number.isFinite(progress) || progress <= 0.025) {
    return { projected: null, risk: "缺少计数" };
  }
  const projected = count / progress;
  const expected = marketImpliedExpected(market);
  if (!Number.isFinite(expected) || expected <= 0) {
    return { projected, risk: "数据不足" };
  }
  const ratio = projected / expected;
  if (ratio >= 1.7) return { projected, risk: "critical" };
  if (ratio >= 1.35) return { projected, risk: "warning" };
  if (ratio <= 0.65) return { projected, risk: "low-tail" };
  return { projected, risk: "normal" };
}

function currentCount() {
  const manual = Number(els.countInput.value);
  if (Number.isFinite(manual) && manual >= 0) return manual;
  const automatic = Number(state.tracker?.count);
  return Number.isFinite(automatic) && automatic >= 0 ? automatic : null;
}

function riskClass(risk) {
  if (risk === "normal") return "good";
  if (risk === "warning" || risk === "low-tail") return "watch";
  if (risk === "critical") return "risk";
  return "";
}

function signalFor(outcome) {
  const ask = Number(outcome.bestAsk ?? outcome.entryPrice);
  const bid = Number(outcome.bestBid);
  const model = Number(outcome.modelProbability);
  const market = marketProbability(outcome);
  const depth = Number(outcome.askDepth || 0) + Number(outcome.bidDepth || 0);
  const target = Number(outcome.limitTarget);
  const settlementEdge = Number(outcome.edge);
  const convergenceEdge = model - (Number.isFinite(market) ? market : ask);
  if (outcome.orderbookStatus !== "live" && depth <= 0) return ["watch", "盘口待刷新"];
  if (settlementEdge >= 0.03) return ["good", "直接建仓"];
  if (settlementEdge >= 0) return ["good", "小仓试单"];
  if (
    Number.isFinite(target) &&
    Number.isFinite(ask) &&
    target < ask &&
    convergenceEdge >= 0.01 &&
    (!Number.isFinite(bid) || target >= bid + 0.001)
  ) {
    return ["watch", "限价挂单"];
  }
  if (convergenceEdge >= 0.03 && depth >= 10) return ["watch", "波段观察"];
  if (convergenceEdge >= 0.01) return ["watch", "等待回落"];
  return ["skip", "跳过"];
}

function marketProbability(outcome) {
  const mid = Number(outcome.midPrice);
  if (Number.isFinite(mid) && mid >= 0) return mid;
  const gamma = Number(outcome.gammaPrice);
  if (Number.isFinite(gamma) && gamma >= 0) return gamma;
  const ask = Number(outcome.bestAsk);
  return Number.isFinite(ask) && ask > 0 ? ask : null;
}

function selectedOutcomes() {
  const market = selectedMarket();
  if (!market) return [];
  return (market.outcomes || []).filter((outcome) => state.selectedIds.has(outcome.id));
}

function autoSelectTop(market) {
  applyModel(market);
  const top = [...(market.outcomes || [])]
    .sort((a, b) => (b.modelProbability || 0) - (a.modelProbability || 0))
    .slice(0, 3);
  state.selectedIds = new Set(top.map((outcome) => outcome.id));
}

function renderMarketList() {
  els.marketCount.textContent = String(state.markets.length);
  const liveCount = state.markets.filter((market) => !market.isSample).length;
  if (els.liveSummary) {
    els.liveSummary.textContent =
      state.source === "live" ? `${liveCount} 个实时市场` : state.source === "loading" ? "正在加载" : "实时不可用";
    els.liveSummary.className = `status-pill ${state.source === "live" ? "live" : "sample"}`;
  }
  const usingSample = state.markets.some((market) => market.isSample);
  const hasError = state.source === "error";
  els.marketNotice.hidden = !usingSample && !hasError && state.source !== "loading";
  if (hasError) {
    els.marketNotice.textContent = `实时市场加载失败：${state.warning || "未知错误"}`;
  } else if (usingSample) {
    els.marketNotice.textContent = "当前显示 Demo 数据：实时 Polymarket 市场发现没有命中，不能作为真实交易依据。";
  } else if (state.source === "loading") {
    els.marketNotice.textContent = "正在加载实时 Polymarket 市场...";
  } else {
    els.marketNotice.textContent = "";
  }
  els.marketList.innerHTML = "";
  if (!state.markets.length) {
    const empty = document.createElement("div");
    empty.className = "record";
    empty.innerHTML = "<strong>暂无实时市场</strong><span>可以点刷新数据，或粘贴 Polymarket 市场 URL / slug 精确加载。</span>";
    els.marketList.appendChild(empty);
    return;
  }
  for (const market of state.markets) {
    const item = document.createElement("div");
    item.className = `market-item ${market.id === state.selectedMarketId ? "active" : ""}`;
    const url = polymarketUrl(market);
    item.innerHTML = `
      <button class="market-select" type="button">
        <strong>${escapeHtml(displayMarketTitle(market))}</strong>
        <span>${market.isSample ? "Demo · " : ""}${escapeHtml(market.periodType || "unknown")} · ${market.outcomes?.length || 0} 个区间</span>
      </button>
      <button class="market-open" type="button" ${url ? "" : "disabled"} title="查看 Polymarket 原始页面">查看详情</button>
    `;
    item.querySelector(".market-select").addEventListener("click", async () => {
      state.selectedMarketId = market.id;
      autoSelectTop(market);
      render();
      await loadTracker(market);
      simulate();
    });
    item.querySelector(".market-open").addEventListener("click", () => {
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    });
    els.marketList.appendChild(item);
  }
}

function renderMarketHeader(market) {
  els.periodLabel.textContent = market ? `${market.periodType || "unknown"} 市场` : "未选择市场";
  els.marketTitle.textContent = market ? displayMarketTitle(market) : "等待市场数据";
  els.volumeMetric.textContent = fmtCompactUsd(Number(market?.volume));
  els.liquidityMetric.textContent = fmtCompactUsd(Number(market?.liquidity));
  const remaining = hoursRemaining(market);
  els.remainingMetric.textContent = Number.isFinite(remaining) ? `${Math.max(0, remaining).toFixed(1)}h` : "-";
}

function renderSummary(market) {
  const projection = projectionState(market);
  if (els.trackerSourceMetric) {
    if (state.manualCount) {
      els.trackerSourceMetric.textContent = "手动覆盖";
    } else if (state.tracker?.count != null) {
      els.trackerSourceMetric.textContent = `XTracker ${state.tracker.count}`;
    } else if (state.tracker?.error) {
      els.trackerSourceMetric.textContent = "不可用";
    } else {
      els.trackerSourceMetric.textContent = "获取中";
    }
  }
  els.projectionMetric.textContent = Number.isFinite(projection.projected) ? fmtNum(projection.projected, 1) : "-";
  els.riskMetric.textContent = {
    normal: "正常",
    warning: "偏高",
    "low-tail": "偏低",
    critical: "高风险",
    缺少计数: "缺少计数",
    数据不足: "数据不足",
  }[projection.risk] || projection.risk;
  els.riskMetric.className = riskClass(projection.risk);

  const sim = state.simulation;
  els.basketCostMetric.textContent = sim ? fmtPct(sim.costPerShare) : "-";
  els.coverMetric.textContent = sim ? fmtPct(sim.coverProbability) : "-";
  els.edgeMetric.textContent = sim ? fmtPct(sim.edge) : "-";
  els.edgeMetric.className = sim ? (sim.edge >= 0 ? "edge-positive" : "edge-negative") : "";
}

function renderOutcomeRows(market) {
  els.outcomeRows.innerHTML = "";
  const selected = selectedOutcomes();
  els.selectedCount.textContent = `${selected.length} 已选`;
  for (const outcome of market?.outcomes || []) {
    const tr = document.createElement("tr");
    const checked = state.selectedIds.has(outcome.id);
    if (checked) tr.classList.add("selected");
    const [signalClass, signalText] = signalFor(outcome);
    const depth = Number(outcome.askDepth || 0) + Number(outcome.bidDepth || 0);
    const marketProb = marketProbability(outcome);
    tr.innerHTML = `
      <td><input type="checkbox" ${checked ? "checked" : ""} /></td>
      <td class="range-cell">${escapeHtml(outcome.label)}</td>
      <td>${fmtPrice(outcome.bestBid)}</td>
      <td>${fmtPrice(outcome.bestAsk)}</td>
      <td>${fmtPrice(outcome.spread)}</td>
      <td>${fmtUsd(depth)}</td>
      <td>${fmtMarketPct(marketProb)}</td>
      <td>${fmtPct(outcome.modelProbability)}</td>
      <td class="${outcome.edge >= 0 ? "edge-positive" : "edge-negative"}">${fmtPct(outcome.edge)}</td>
      <td><span class="signal ${signalClass}">${signalText}</span></td>
    `;
    tr.querySelector("input").addEventListener("change", (event) => {
      if (event.target.checked) {
        state.selectedIds.add(outcome.id);
      } else {
        state.selectedIds.delete(outcome.id);
      }
      render();
      simulate();
    });
    els.outcomeRows.appendChild(tr);
  }
}

function renderSimulation() {
  const sim = state.simulation;
  const status = sim?.status || "idle";
  const label = sim
    ? status === "limit-order"
      ? sim.limitAdvice || status
      : status === "swing-watch"
        ? sim.swingAdvice || status
        : sim.settlementAdvice || status
    : "等待选择";
  els.simulationStatus.textContent = label;
  els.simulationStatus.className = "soft-pill";
  if (status === "normal-size" || status === "small-size") els.simulationStatus.classList.add("live");
  if (status === "watch" || status === "limit-order" || status === "swing-watch") {
    els.simulationStatus.classList.add("sample");
  }
  els.settlementAdviceValue.textContent = sim ? sim.settlementAdvice : "-";
  els.limitAdviceValue.textContent = sim ? sim.limitAdvice : "-";
  els.swingAdviceValue.textContent = sim ? sim.swingAdvice : "-";
  els.sharesValue.textContent = sim ? fmtNum(sim.shares, 2) : "-";
  els.costValue.textContent = sim ? fmtUsd(sim.cost) : "-";
  els.profitValue.textContent = sim ? fmtUsd(sim.profitIfHit) : "-";
  els.lossValue.textContent = sim ? fmtUsd(sim.maxLoss) : "-";
  els.evValue.textContent = sim ? fmtUsd(sim.expectedValue) : "-";
  els.targetExitValue.textContent = sim ? fmtPct(sim.targetExitPrice) : "-";
  els.targetEntryValue.textContent = sim ? fmtPct(sim.targetEntryCost) : "-";
  els.swingValue.textContent = sim ? fmtUsd(sim.swingReturn) : "-";
  const hasSelection = selectedOutcomes().length > 0;
  els.paperBtn.disabled = !hasSelection;
  els.draftBtn.disabled = !hasSelection;
}

function render() {
  const market = selectedMarket();
  if (market) applyModel(market);
  renderMarketList();
  renderMarketHeader(market);
  renderSummary(market);
  renderOutcomeRows(market);
  renderSimulation();
}

async function simulate() {
  const market = selectedMarket();
  if (!market) return;
  const selected = selectedOutcomes();
  if (!selected.length) {
    state.simulation = null;
    render();
    return;
  }
  const body = simulationBody();
  try {
    const response = await fetch("/api/basket/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.simulation = await response.json();
    render();
  } catch (error) {
    showToast(`模拟失败：${error.message}`);
  }
}

async function loadTracker(market) {
  state.tracker = null;
  state.manualCount = false;
  els.countInput.value = "";
  els.countInput.placeholder = "自动获取中";
  if (!market || market.isSample) {
    state.tracker = { error: "No live market" };
    els.countInput.placeholder = "手动覆盖";
    render();
    return;
  }
  const params = new URLSearchParams({
    slug: market.slug || "",
    startTime: market.startTime || "",
    endTime: market.endTime || "",
  });
  try {
    const response = await fetch(`/api/tracker?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "xtracker unavailable");
    }
    state.tracker = payload;
    els.countInput.value = payload.count;
    els.countInput.placeholder = "手动覆盖";
  } catch (error) {
    state.tracker = { error: error.message };
    els.countInput.value = "";
    els.countInput.placeholder = "自动失败，可手动填";
    showToast(`xtracker 计数获取失败：${error.message}`);
  }
  render();
  simulate();
}

function simulationBody() {
  const market = selectedMarket();
  return {
    marketId: market?.id,
    marketTitle: market?.title,
    strategyType: els.strategyInput.value,
    budget: Number(els.budgetInput.value || 0),
    bufferPct: Number(els.bufferInput.value || 0),
    selectedOutcomes: selectedOutcomes(),
  };
}

async function loadMarkets(refresh = false) {
  state.loading = true;
  state.source = "loading";
  state.warning = null;
  els.sourceBadge.textContent = "加载中";
  els.sourceBadge.className = "status-pill";
  renderMarketList();
  try {
    const response = await fetch(`/api/markets${refresh ? "?refresh=1" : ""}`);
    const payload = await response.json();
    state.source = payload.source || "unknown";
    state.warning = payload.warning || null;
    state.markets = payload.markets || [];
    state.selectedMarketId = state.markets[0]?.id || null;
    if (state.markets[0]) autoSelectTop(state.markets[0]);
    els.sourceBadge.textContent = payload.source === "live" ? "实时数据" : "实时异常";
    els.sourceBadge.className = `status-pill ${payload.source === "live" ? "live" : "sample"}`;
    if (payload.warning) showToast(`实时数据加载失败：${payload.warning}`);
    render();
    await loadTracker(state.markets[0]);
    await simulate();
  } catch (error) {
    state.source = "error";
    state.warning = error.message;
    state.markets = [];
    showToast(`加载失败：${error.message}`);
    render();
  } finally {
    state.loading = false;
  }
}

async function resolveMarket() {
  const value = els.marketUrlInput.value.trim();
  if (!value) {
    showToast("请先粘贴 Polymarket 市场 URL 或 slug");
    return;
  }
  els.resolveMarketBtn.disabled = true;
  try {
    const response = await fetch(`/api/resolve-market?input=${encodeURIComponent(value)}`);
    const payload = await response.json();
    if (!response.ok || !payload.market) {
      throw new Error(payload.error || "无法解析市场");
    }
    const market = payload.market;
    state.markets = [market, ...state.markets.filter((item) => item.id !== market.id)];
    state.selectedMarketId = market.id;
    state.source = "live";
    state.warning = null;
    autoSelectTop(market);
    els.sourceBadge.textContent = "已加载实盘";
    els.sourceBadge.className = "status-pill live";
    render();
    await loadTracker(market);
    await simulate();
    showToast("真实市场已加载");
  } catch (error) {
    showToast(`加载失败：${error.message}`);
  } finally {
    els.resolveMarketBtn.disabled = false;
  }
}

async function savePaperTrade() {
  try {
    const response = await fetch("/api/paper-trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(simulationBody()),
    });
    if (!response.ok) throw new Error("request failed");
    showToast("模拟记录已保存");
    await loadPaperTrades();
  } catch (error) {
    showToast(`记录失败：${error.message}`);
  }
}

async function saveOrderDraft() {
  try {
    const response = await fetch("/api/order-drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(simulationBody()),
    });
    if (!response.ok) throw new Error("request failed");
    showToast("下单建议已生成，未提交实盘");
  } catch (error) {
    showToast(`草稿失败：${error.message}`);
  }
}

async function loadPaperTrades() {
  try {
    const response = await fetch("/api/paper-trades");
    const payload = await response.json();
    renderPaperTrades(payload.items || []);
  } catch (error) {
    showToast(`模拟交易记录加载失败：${error.message}`);
  }
}

function renderPaperTrades(items) {
  els.paperTradeList.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "record";
    empty.innerHTML = "<strong>暂无记录</strong><span>模拟交易记录会显示在这里</span>";
    els.paperTradeList.appendChild(empty);
    return;
  }
  for (const item of items) {
    const record = document.createElement("div");
    record.className = "record";
    const labels = (item.selectedOutcomes || []).map((outcome) => outcome.label).join(", ");
    record.innerHTML = `
      <strong>${escapeHtml(item.strategyType)} · ${fmtPct(item.edge)}</strong>
      <span>${escapeHtml(labels)}</span>
      <span>${fmtUsd(Number(item.cost))} · 命中 ${fmtPct(Number(item.coverProbability))}</span>
    `;
    els.paperTradeList.appendChild(record);
  }
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 4200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let inputTimer = null;
function queueRecompute() {
  window.clearTimeout(inputTimer);
  inputTimer = window.setTimeout(() => {
    render();
    simulate();
  }, 180);
}

function onCountInput() {
  state.manualCount = true;
  queueRecompute();
}

els.refreshBtn.addEventListener("click", () => loadMarkets(true));
els.resolveMarketBtn.addEventListener("click", resolveMarket);
els.marketUrlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") resolveMarket();
});
els.paperBtn.addEventListener("click", savePaperTrade);
els.draftBtn.addEventListener("click", saveOrderDraft);
els.reloadTradesBtn.addEventListener("click", loadPaperTrades);
els.countInput.addEventListener("input", onCountInput);
els.budgetInput.addEventListener("input", queueRecompute);
els.bufferInput.addEventListener("input", queueRecompute);
els.strategyInput.addEventListener("change", queueRecompute);

loadMarkets(false);
loadPaperTrades();
