// Dashboard logic. Reads data.json (built daily by build_site.py) and does the interactive
// math in the browser: the rebalancing simulator and the DCF playground mirror the Python
// formulas in risk.py, stress.py, and dcf.py.
"use strict";

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = { ink: css("--ink"), muted: css("--muted"), faint: css("--faint"), rule: css("--rule"),
  accent: css("--accent"), up: css("--up"), down: css("--down"), amber: css("--amber"),
  shadow: css("--shadow"), spx: "#b8b1a3" };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x, d = 1) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}%`);
const signed = (x, d = 1, txt) => (x == null ? "–" : `<span class="${x >= 0 ? "up" : "down"}">${txt ?? pct(x, d)}</span>`);
const fmtDate = (s) => new Date(s + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

let D;

fetch("data.json").then((r) => r.json()).then((data) => {
  D = data;
  $("updated").textContent = `Updated ${D.generated}`;
  $("footer").textContent = `Data as of ${D.generated}. Not investment advice.`;
  Chart.defaults.font.family = css("--sans");
  Chart.defaults.font.size = 11;
  Chart.defaults.color = C.faint;
  renderToday();
  renderPortfolio();
  initSimulator();
  initDCF();
  renderHistory();
  renderCatalysts();
  renderLetters();
  applyDeepLink();
}).catch((e) => { $("updated").textContent = "Could not load data: " + e; });

// Links from the email open the dashboard at the matching spot:
//   ?dcf=AAPL#valuation, ?preset=Conservative#simulator, ?letter=2026-10-21#letters
function applyDeepLink() {
  const q = new URLSearchParams(location.search);
  let target = location.hash ? document.querySelector(location.hash) : null;
  const dcf = (q.get("dcf") || "").toUpperCase();
  const i = D.dcf.findIndex((d) => d.ticker === dcf);
  if (i >= 0) { $("dcf-ticker").value = i; loadDCF(i); }
  const preset = q.get("preset");
  if (preset && D.presets[preset]) { setMix(D.presets[preset]); markPreset(preset); syncSliders(); updateSim(); }
  const day = q.get("letter");
  if (day) {
    const el = document.querySelector(`#archive details[data-date="${CSS.escape(day)}"]`);
    if (el) {
      $("archive").querySelectorAll("details").forEach((d) => (d.hidden = false));
      $("archive").querySelector(".more")?.remove();
      el.open = true;
      target = el;
    }
  }
  // Content renders after the browser's own jump to the #anchor, so jump again now
  if (target) requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
}

// ---------- today ----------
function renderToday() {
  const w = D.weather;
  const color = { Calm: C.up, Mixed: C.amber, Stressed: C.down }[w.name];
  const shapes = ["●", "▲", "■"], colors = [C.up, C.amber, C.down];
  $("weather").innerHTML =
    `<div class="weather-name" style="color:${color}">${w.name}
       <span class="small muted">${w.flags} of ${w.signals.length} signals flagged · ● ok ▲ caution ■ stress</span></div>` +
    w.signals.map((s) => `<div class="signal"><span style="color:${colors[s.level]}">${shapes[s.level]}</span>
       <b>${esc(s.name)}</b><div>${esc(s.reading)}${s.level ? `<div class="why">${esc(s.why)}</div>` : ""}</div></div>`).join("");
  const latest = D.letters.find((l) => l.take);
  if (latest) {
    $("take-date").textContent = fmtDate(latest.date);
    $("take").textContent = latest.take;
    $("watch").innerHTML = (latest.watch || []).map((x) => `<div class="watch">${esc(x)}</div>`).join("");
  }
}

// ---------- portfolio ----------
function tile(k, v, s) { return `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`; }

function renderPortfolio() {
  const r = D.risk;
  $("tiles").innerHTML = [
    tile("1-year return", signed(r.ret_1y), `S&amp;P ${pct(r.spx_ret_1y)}`),
    tile("Beta", r.beta.toFixed(2), "S&amp;P = 1.00"),
    tile("Volatility", `${r.vol.toFixed(0)}%`, `S&amp;P ${r.spx_vol.toFixed(0)}%`),
    tile("Sharpe ratio", r.sharpe.toFixed(2), `S&amp;P ${r.spx_sharpe.toFixed(2)}`),
    tile("Bad day", `−${r.var_pct.toFixed(1)}%`, "1-in-20 day loss"),
    tile("From peak", pct(r.off_peak), `Worst ${pct(r.max_dd)}`),
    tile("AI &amp; big tech", `${(D.ai_exposure ?? 0).toFixed(0)}%`, "incl. inside funds"),
  ].join("");
  const max = Math.max(...D.weights.map((w) => w.weight));
  $("holdings").innerHTML = `<tr><th>Holding</th><th>Weight</th><th>Day</th><th>Since bought</th></tr>` +
    D.weights.map((w) => `<tr><td><b>${w.cash ? "Cash" : esc(w.ticker)}</b></td>
      <td><span class="bar" style="width:${(w.weight / max) * 60}px"></span>${w.weight < 1 ? "&lt;1" : w.weight.toFixed(0)}%</td>
      <td>${w.cash ? "" : signed(w.day_pct, 2)}</td><td>${w.cash ? "" : signed(w.gain_pct)}</td></tr>`).join("");
  const e = D.exposure;
  $("sectors").innerHTML = `<tr><th>Sector</th><th>You</th><th>vs S&amp;P</th></tr>` +
    Object.entries(e.sectors).filter(([s]) => s !== "Cash").slice(0, 8).map(([s, v]) =>
      `<tr><td>${esc(s)}</td><td><span class="bar" style="width:${v * 1.6}px"></span>${v.toFixed(0)}%</td>
       <td>${signed(v - (e.benchmark[s] ?? 0), 0, `${v - (e.benchmark[s] ?? 0) >= 0 ? "+" : "−"}${Math.abs(v - (e.benchmark[s] ?? 0)).toFixed(0)} pts`)}</td></tr>`).join("");
  $("regions").innerHTML = "Regions: " + Object.entries(e.regions).filter(([, v]) => v >= 0.5)
    .map(([k, v]) => `${esc(k)} ${v.toFixed(0)}%`).join(" · ") +
    "<br>Biggest companies counting fund holdings: " + e.top.map((c) => `${esc(c.name)} ${c.pct.toFixed(1)}%`).join(" · ");
}

// ---------- simulator ----------
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const std = (a) => { const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); };
const cov = (a, b) => { const ma = mean(a), mb = mean(b); return a.reduce((s, x, i) => s + (x - ma) * (b[i] - mb), 0) / (a.length - 1); };
function quantile(a, q) { // linear interpolation, same as pandas
  const s = [...a].sort((x, y) => x - y), pos = (s.length - 1) * q, lo = Math.floor(pos);
  return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (pos - lo);
}

function mixStats(weights) {
  const total = Object.values(weights).reduce((s, x) => s + x, 0);
  if (!total) return null;
  const blocks = D.blocks.filter((b) => weights[b.ticker] > 0);
  const n = D.spx_returns.length;
  const rp = Array.from({ length: n }, (_, t) => blocks.reduce((s, b) => s + (weights[b.ticker] / total) * b.returns[t], 0));
  let level = 1, peak = 1, maxDD = 0;
  const path = [100];
  for (const r of rp) { level *= 1 + r; peak = Math.max(peak, level); maxDD = Math.min(maxDD, level / peak - 1); path.push(level * 100); }
  const ret = level - 1, vol = std(rp) * Math.sqrt(252);
  const replays = Object.fromEntries(D.scenarios.map((sc) => [sc, blocks.reduce((s, b) =>
    s + (weights[b.ticker] / total) * (b.replays[sc] ?? D.spx_replays[sc]), 0)]));
  return {
    ret: ret * 100, vol: vol * 100, beta: cov(rp, D.spx_returns) / std(D.spx_returns) ** 2,
    sharpe: (ret - D.rf) / vol, var: -quantile(rp, 0.05) * 100, maxDD: maxDD * 100,
    ai: blocks.reduce((s, b) => s + (weights[b.ticker] / total) * b.ai, 0) * 100, replays, path,
  };
}

let mix = {}, simChart;

function initSimulator() {
  const current = D.presets.Current;
  const held = Object.keys(current);
  const order = [...held, ...D.blocks.map((b) => b.ticker).filter((t) => !held.includes(t))];
  const byTicker = Object.fromEntries(D.blocks.map((b) => [b.ticker, b]));
  let html = `<div class="group">Your holdings</div>`;
  order.forEach((t, i) => {
    if (i === held.length) html += `<div class="group">Other building blocks</div>`;
    const b = byTicker[t];
    if (!b) return;
    html += `<div class="slider"><label for="w-${t}"><b>${esc(t)}</b> <span class="muted">${esc(b.name)}</span></label>
      <output id="o-${t}"></output><input type="range" id="w-${t}" min="0" max="60" step="1" data-t="${t}"></div>`;
  });
  $("sliders").innerHTML = html;
  $("sliders").addEventListener("input", (e) => {
    if (e.target.dataset.t) { mix[e.target.dataset.t] = +e.target.value; markPreset(null); updateSim(); }
  });
  $("presets").innerHTML = Object.keys(D.presets).map((p) => `<button data-p="${esc(p)}">${esc(p)}</button>`).join("") +
    `<button data-p="__norm" class="ghost" style="margin:0">Scale to 100%</button>`;
  $("presets").addEventListener("click", (e) => {
    const p = e.target.dataset.p;
    if (!p) return;
    if (p === "__norm") {
      const tot = Object.values(mix).reduce((s, x) => s + x, 0) || 1;
      for (const t in mix) mix[t] = Math.round((mix[t] / tot) * 100);
    } else { setMix(D.presets[p]); markPreset(p); }
    syncSliders(); updateSim();
  });
  simChart = new Chart($("sim-chart"), lineConfig());
  setMix(D.presets.Conservative ? D.presets.Conservative : current);
  markPreset(D.presets.Conservative ? "Conservative" : "Current");
  syncSliders(); updateSim();
}

function setMix(w) { mix = {}; D.blocks.forEach((b) => (mix[b.ticker] = Math.round((w[b.ticker] || 0) * 100))); }
function markPreset(p) { document.querySelectorAll("#presets button[data-p]").forEach((b) => b.classList.toggle("on", b.dataset.p === p)); }
function syncSliders() { for (const t in mix) { const el = $("w-" + t); if (el) el.value = mix[t]; } }

function updateSim() {
  for (const t in mix) { const o = $("o-" + t); if (o) o.textContent = mix[t] + "%"; }
  const total = Object.values(mix).reduce((s, x) => s + x, 0);
  $("total").innerHTML = `Total <b>${total}%</b>` + (total !== 100 && total ? " · stats scale it to 100%" : "");
  const cur = mixStats(Object.fromEntries(Object.entries(D.presets.Current).map(([t, w]) => [t, w * 100])));
  const m = mixStats(mix);
  if (!m) { $("compare").innerHTML = ""; return; }
  const row = (k, a, b) => `<tr><td>${k}</td><td>${a}</td><td class="mix">${b}</td></tr>`;
  $("compare").innerHTML = `<tr><th></th><th>Current</th><th class="mix">Your mix</th></tr>` +
    row("1-year return", signed(cur.ret), signed(m.ret)) +
    row("Volatility", cur.vol.toFixed(1) + "%", m.vol.toFixed(1) + "%") +
    row("Beta", cur.beta.toFixed(2), m.beta.toFixed(2)) +
    row("Bad day (1 in 20)", "−" + cur.var.toFixed(2) + "%", "−" + m.var.toFixed(2) + "%") +
    row("Worst drop", pct(cur.maxDD), pct(m.maxDD)) +
    row("Sharpe ratio", cur.sharpe.toFixed(2), m.sharpe.toFixed(2)) +
    row("AI &amp; big tech", cur.ai.toFixed(0) + "%", m.ai.toFixed(0) + "%") +
    D.scenarios.map((sc) => row(esc(sc), signed(cur.replays[sc] * 100), signed(m.replays[sc] * 100))).join("");
  const spxPath = [100];
  D.spx_returns.forEach((r) => spxPath.push(spxPath[spxPath.length - 1] * (1 + r)));
  const labels = D.performance["S&P 500"].dates.slice(-spxPath.length);
  simChart.data.labels = labels;
  simChart.data.datasets = [
    ds("S&P 500", spxPath, C.spx, 1.3), ds("Current", cur.path, C.accent, 2), ds("Your mix", m.path, C.shadow, 2, [5, 3]),
  ];
  simChart.update("none");
  $("sim-legend").innerHTML = legend([["Current", C.accent], ["Your mix", C.shadow, true], ["S&P 500", C.spx]]);
}

// ---------- charts ----------
function ds(label, data, color, width, dash) {
  return { label, data, borderColor: color, backgroundColor: color, borderWidth: width, borderDash: dash || [],
    pointRadius: 0, pointHoverRadius: 3, tension: 0 };
}
function lineConfig(yfmt = (v) => v.toFixed(0)) {
  return {
    type: "line", data: { labels: [], datasets: [] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: "#1b1b1b", padding: 8, displayColors: true,
        callbacks: { title: (it) => fmtDate(it[0].label), label: (c) => ` ${c.dataset.label}: ${yfmt(c.parsed.y)}` } } },
      scales: {
        x: { grid: { display: false }, border: { color: C.rule },
          ticks: { maxTicksLimit: 7, autoSkip: true, maxRotation: 0,
            callback(v) { const d = this.getLabelForValue(v); return d ? new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short" }) : ""; } } },
        y: { position: "right", grid: { color: "#efebe2" }, border: { display: false }, ticks: { maxTicksLimit: 5, callback: yfmt } },
      },
    },
  };
}
function legend(items) {
  return items.map(([name, color, dash]) => `<span class="sw${dash ? " dash" : ""}" style="${dash ? "" : `background:${color}`}"></span>${esc(name)}`).join("");
}

// ---------- DCF ----------
const DCF_SLIDERS = [
  ["g1", "Revenue growth, year 1", -10, 40, 0.5, "%"],
  ["g2", "Revenue growth, year 2", -10, 40, 0.5, "%"],
  ["margin", "Free cash flow margin", 1, 60, 0.5, "%"],
  ["wacc", "Discount rate (WACC)", 4, 16, 0.1, "%"],
  ["tg", "Long-run growth", 0, 4, 0.1, "%"],
];
let dcfInput, dcfState = {};

function initDCF() {
  if (!D.dcf.length) { $("valuation").style.display = "none"; return; }
  $("dcf-ticker").innerHTML = D.dcf.map((d, i) => `<option value="${i}">${esc(d.name)} (${esc(d.ticker)})</option>`).join("");
  $("dcf-sliders").innerHTML = DCF_SLIDERS.map(([k, name, lo, hi, step]) =>
    `<div class="slider"><label for="d-${k}">${name}</label><output id="do-${k}"></output>
     <input type="range" id="d-${k}" min="${lo}" max="${hi}" step="${step}" data-k="${k}"></div>`).join("");
  $("dcf-sliders").addEventListener("input", (e) => { if (e.target.dataset.k) { dcfState[e.target.dataset.k] = +e.target.value; updateDCF(); } });
  $("dcf-ticker").addEventListener("change", () => loadDCF(+$("dcf-ticker").value));
  $("dcf-reset").addEventListener("click", () => loadDCF(+$("dcf-ticker").value));
  loadDCF(0);
}

function loadDCF(i) {
  dcfInput = D.dcf[i];
  dcfState = { g1: dcfInput.growth[0] * 100, g2: dcfInput.growth[1] * 100, margin: dcfInput.fcf_margin * 100,
    wacc: dcfInput.wacc * 100, tg: D.terminal_growth * 100 };
  for (const [k, , lo, hi, step] of DCF_SLIDERS) {
    dcfState[k] = Math.min(hi, Math.max(lo, Math.round(dcfState[k] / step) * step));
    $("d-" + k).value = dcfState[k];
  }
  updateDCF();
}

function dcfValue(inp, s, growth) {
  const r = s.wacc / 100, tg = s.tg / 100, Y = D.years;
  if (r <= tg) return null;
  if (!growth) {
    const g1 = s.g1 / 100, g2 = s.g2 / 100;
    growth = [g1, g2, ...Array.from({ length: Y - 2 }, (_, k) => g2 + ((tg - g2) * (k + 1)) / (Y - 2))];
  }
  let rev = inp.revenue, pvSum = 0, fcf = 0;
  const rows = growth.map((g, j) => { rev *= 1 + g; fcf = rev * (s.margin / 100); const pv = fcf / (1 + r) ** (j + 1); pvSum += pv; return { year: j + 1, g, rev, fcf, pv }; });
  const pvTV = ((fcf * (1 + tg)) / (r - tg)) / (1 + r) ** Y;
  const ev = pvSum + pvTV, perShare = (ev - inp.debt + inp.cash) / inp.shares;
  return { perShare, ev, tvShare: pvTV / ev, rows };
}

function impliedGrowth(inp, s) {
  let lo = -0.3, hi = 0.8;
  const f = (g) => dcfValue(inp, s, Array(D.years).fill(g)).perShare - inp.price;
  if (f(lo) > 0 || f(hi) < 0) return null;
  for (let k = 0; k < 60; k++) { const mid = (lo + hi) / 2; f(mid) < 0 ? (lo = mid) : (hi = mid); }
  return (lo + hi) / 2;
}

function updateDCF() {
  for (const [k] of DCF_SLIDERS) $("do-" + k).textContent = dcfState[k].toFixed(1) + "%";
  const inp = dcfInput, v = dcfValue(inp, dcfState);
  const B = (x) => "$" + (x / 1e9).toLocaleString("en-US", { maximumFractionDigits: x >= 1e10 ? 0 : 1 }) + "B";
  if (!v) { $("dcf-tiles").innerHTML = tile("DCF value", "n/a", "discount rate must exceed long-run growth"); return; }
  const up = v.perShare / inp.price - 1, ig = impliedGrowth(inp, dcfState);
  $("dcf-tiles").innerHTML = tile("Share price", "$" + inp.price.toFixed(2), esc(inp.ticker)) +
    tile("DCF value", "$" + v.perShare.toFixed(0), signed(up * 100, 0) + " vs price") +
    tile("Terminal value", (v.tvShare * 100).toFixed(0) + "%", "of enterprise value");
  $("dcf-implied").innerHTML = ig == null ? "No growth rate in range justifies today's price."
    : `With these discount rates, today's price implies <b>${(ig * 100).toFixed(1)}%</b> revenue growth a year for ${D.years} years. Analysts expect ${(inp.growth[0] * 100).toFixed(1)}% this year and ${(inp.growth[1] * 100).toFixed(1)}% next.`;
  $("dcf-table").innerHTML = `<tr><th>Year</th><th>Growth</th><th>Revenue</th><th>Free cash flow</th><th>Present value</th></tr>` +
    v.rows.filter((r) => [1, 2, 3, 5, 10].includes(r.year)).map((r) =>
      `<tr><td>${r.year}</td><td>${(r.g * 100).toFixed(1)}%</td><td>${B(r.rev)}</td><td>${B(r.fcf)}</td><td>${B(r.pv)}</td></tr>`).join("");
  $("dcf-note").innerHTML = `FY${esc(inp.fiscal_year)} revenue ${B(inp.revenue)} · model WACC ${(inp.wacc * 100).toFixed(1)}%: cost of equity ${(inp.cost_of_equity * 100).toFixed(1)}% = ${(inp.rf * 100).toFixed(2)}% 10-year Treasury + ${inp.beta.toFixed(2)} beta × ${(D.erp * 100).toFixed(0)}% equity risk premium · debt ${B(inp.debt)}, cash ${B(inp.cash)}.`;
}

// ---------- history ----------
function renderHistory() {
  const p = D.performance, names = Object.keys(p);
  const chart = new Chart($("perf-chart"), lineConfig());
  const styles = { You: [C.accent, 2], "S&P 500": [C.spx, 1.3] };
  chart.data.labels = p["S&P 500"].dates;
  const byDate = (s) => { const m = Object.fromEntries(s.dates.map((d, i) => [d, s.values[i]])); return p["S&P 500"].dates.map((d) => m[d] ?? null); };
  chart.data.datasets = names.map((n) => {
    const [color, width] = styles[n] || [C.shadow, 1.6];
    return ds(n, byDate(p[n]), color, width, styles[n] ? null : [5, 3]);
  });
  chart.update();
  const last = (n) => p[n].values[p[n].values.length - 1] - 100;
  $("perf-legend").innerHTML = names.map((n) => {
    const [color] = styles[n] || [C.shadow];
    return `<span class="sw${styles[n] ? "" : " dash"}" style="${styles[n] ? `background:${color}` : ""}"></span>${esc(n)} ${signed(last(n))}`;
  }).join("");

  const daily = D.daily.filter((d) => d.regime_score != null);
  const small = (canvas, label, values, color, fmt, max) => {
    const cfg = lineConfig(fmt);
    cfg.data.labels = daily.map((d) => d.date);
    cfg.data.datasets = [{ ...ds(label, values, color, 2), pointRadius: 2.5 }];
    cfg.options.scales.x.ticks.callback = function (v) { const d = this.getLabelForValue(v); return d ? new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""; };
    if (max != null) { cfg.options.scales.y.min = 0; cfg.options.scales.y.max = max; }
    new Chart(canvas, cfg);
  };
  small($("regime-chart"), "Regime score", daily.map((d) => d.regime_score), C.amber, (v) => v.toFixed(0), 14);
  small($("ai-chart"), "AI exposure", daily.map((d) => d.ai_exposure_pct), C.accent, (v) => v.toFixed(0) + "%");

  const vals = [...D.valuations].reverse();
  $("valuations").innerHTML = vals.length ? `<tr><th>Date</th><th>Company</th><th>Price</th><th>DCF value</th><th>Price implies</th><th>Analysts yr 1</th></tr>` +
    vals.map((v) => `<tr><td>${fmtDate(v.date)}</td><td><b>${esc(v.ticker)}</b></td><td>$${v.price.toFixed(2)}</td>
      <td>$${v.model_value.toFixed(0)} ${signed(v.upside_pct, 0)}</td><td>${v.implied_growth_pct == null ? "–" : v.implied_growth_pct.toFixed(1) + "% a year"}</td>
      <td>${v.growth_y1_pct.toFixed(1)}%</td></tr>`).join("") : "<tr><td>No Deep Dives yet.</td></tr>";
}

// ---------- catalysts ----------
function renderCatalysts() {
  const rows = D.catalysts || [];
  if (!rows.length) { $("cat-table").innerHTML = "<tr><td>No catalysts logged yet.</td></tr>"; return; }
  const types = ["All", ...new Set(rows.map((r) => r.type).filter(Boolean))];
  const sources = { holding: "Holding", watchlist: "Watchlist", mover: "Mover", market: "Market" };
  $("cat-filters").innerHTML = types.map((t) => `<button data-t="${esc(t)}">${esc(t)}</button>`).join("");
  const draw = (type) => {
    document.querySelectorAll("#cat-filters button").forEach((b) => b.classList.toggle("on", b.dataset.t === type));
    const shown = rows.filter((r) => type === "All" || r.type === type).slice(0, 60);
    $("cat-table").innerHTML = `<tr><th>Date</th><th>Type</th><th>Company</th><th>Headline</th><th>Move</th></tr>` +
      shown.map((r) => `<tr><td>${fmtDate(r.date)}</td><td><span class="tag">${esc(r.type || "News")}</span></td>
        <td><b>${esc(r.ticker || "–")}</b><br><span class="small muted">${sources[r.source] || ""}</span></td>
        <td class="name">${/^https?:\/\//.test(r.link || "") ? `<a href="${esc(r.link)}" rel="noopener">${esc(r.headline)}</a>` : esc(r.headline)}</td>
        <td>${r.day_pct == null ? "" : signed(r.day_pct)}</td></tr>`).join("");
  };
  $("cat-filters").addEventListener("click", (e) => e.target.dataset.t && draw(e.target.dataset.t));
  draw("All");
}

// ---------- letters ----------
const ARCHIVE_SHOWN = 5;

function firstSentence(text, max = 150) {
  const m = text.match(/^.+?[.!?](?=\s|$)/);
  const s = m ? m[0] : text;
  return s.length > max ? s.slice(0, max).replace(/\s+\S*$/, "") + "…" : s;
}

function renderLetters() {
  const letters = D.letters.filter((l) => l.take);
  const item = (l, i) => `<details class="letter" data-date="${esc(l.date)}"${i >= ARCHIVE_SHOWN ? " hidden" : ""}>
    <summary><span class="d">${fmtDate(l.date)}</span><span class="headline">${esc(firstSentence(l.take))}</span></summary>
    <div class="body"><p>${esc(l.take)}</p>
      ${l.portfolio ? `<p><i>${esc(l.portfolio)}</i></p>` : ""}
      ${(l.watch || []).length ? `<p><b>To watch:</b> ${l.watch.map(esc).join(" · ")}</p>` : ""}
      ${l.deep_dive ? `<p><b>Deep Dive:</b> ${esc(l.deep_dive)}</p>` : ""}
      ${(l.movers || []).length ? `<p class="small muted">Movers: ${l.movers.map((m) => `${esc(m.ticker)} ${pct(m.day_pct)}`).join(" · ")}</p>` : ""}
    </div></details>`;
  const older = letters.length - ARCHIVE_SHOWN;
  $("archive").innerHTML =
    `<div class="archive-tools"><span class="small muted">${letters.length} letter${letters.length === 1 ? "" : "s"}</span>
       <button class="ghost" data-a="open">Expand all</button><button class="ghost" data-a="close">Collapse all</button></div>` +
    letters.map(item).join("") +
    (older > 0 ? `<button class="ghost more" data-a="more">Show ${older} older letter${older === 1 ? "" : "s"}</button>` : "");
  $("archive").addEventListener("click", (e) => {
    const a = e.target.dataset.a;
    if (!a) return;
    const all = [...$("archive").querySelectorAll("details")];
    if (a === "more") { all.forEach((d) => (d.hidden = false)); e.target.remove(); }
    else all.filter((d) => !d.hidden).forEach((d) => (d.open = a === "open"));
  });
}
