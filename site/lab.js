// DCF Lab: a five-year unlevered free cash flow model built step by step from archived
// fundamentals (lab.json, built by build_site.py). The same model is written to Excel with
// live formulas by exportXlsx(), so the page and the workbook always agree.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const B = (x) => (x == null ? "–" : `${x < 0 ? "−" : ""}$${(Math.abs(x) / 1e9).toFixed(Math.abs(x) >= 1e11 ? 0 : 1)}B`);
const P = (x, d = 1) => (x == null || !isFinite(x) ? "–" : `${x < 0 ? "−" : ""}${Math.abs(x * 100).toFixed(d)}%`);
const signedPct = (x, d = 0) => `<span class="${x >= 0 ? "up" : "down"}">${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(d)}%</span>`;
const avg = (a) => { const v = a.filter((x) => x != null && isFinite(x)); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
const median = (a) => { const v = a.filter((x) => x != null && isFinite(x)).sort((x, y) => x - y); return v.length ? v[Math.floor((v.length - 1) / 2)] : null; };
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const YEARS = 5;

// Short, company-specific context shown alongside the generic lessons
const NOTES = {
  MCD: {
    s1: "McDonald's owns or leases the land under most of its restaurants and franchises about 95% of them, collecting rent and royalties. That is why its operating margin is around 45%, several times a typical restaurant's. Its shareholder equity is negative: years of buybacks and dividends larger than profits shrank the book value below zero. That reflects how it is financed, not a business in trouble.",
    s4: "McDonald's beta is unusually low (people buy burgers in recessions too), which gives it a low cost of equity. Its debt includes long-term borrowings used to fund buybacks; analysts often also count lease obligations as debt.",
    s5: "Mature consumer brands like McDonald's often trade around 15 to 20 times EBITDA. Check that your two terminal value methods land in the same neighborhood.",
  },
};

let LAB, co, state, hist;

fetch("lab.json").then((r) => r.json()).then((data) => {
  LAB = data;
  $("lab-ticker").innerHTML = LAB.companies.map((c, i) => `<option value="${i}">${esc(c.name)} (${esc(c.ticker)})</option>`).join("");
  const want = new URLSearchParams(location.search).get("company");
  const start = Math.max(0, LAB.companies.findIndex((c) => c.ticker === (want || "").toUpperCase()));
  $("lab-ticker").value = start;
  $("lab-ticker").addEventListener("change", () => load(+$("lab-ticker").value));
  $("lab-reset").addEventListener("click", () => { state = defaults(); save(); renderInputs(); update(); });
  $("lab-xlsx").addEventListener("click", exportXlsx);
  document.querySelector("main").addEventListener("input", onInput);
  document.querySelector("main").addEventListener("click", onToggle);
  load(start);
}).catch((e) => { $("result-bar").innerHTML = `<div class="wrap">Could not load data: ${esc(e)}</div>`; });

// ---------- history and defaults ----------
function history() {
  const ys = Object.values(co.years).sort((a, b) => a.fy.localeCompare(b.fy));
  return ys.map((y, i) => {
    const prev = ys[i - 1];
    const dRev = prev ? y.revenue - prev.revenue : null;
    const fcff = y.ebit != null && y.tax_rate != null && y.da != null && y.capex != null && y.nwc_investment != null
      ? y.ebit * (1 - y.tax_rate) + y.da - y.capex - y.nwc_investment : null;
    return { ...y, growth: prev ? y.revenue / prev.revenue - 1 : null, margin: y.ebit / y.revenue,
      daPct: y.da / y.revenue, capexPct: y.capex / y.revenue, fcff,
      nwcPct: dRev && Math.abs(dRev) > 0.01 * y.revenue && y.nwc_investment != null ? y.nwc_investment / dRev : null };
  });
}

function defaults() {
  const last3 = hist.slice(-3), last = hist[hist.length - 1], first = hist[0];
  const cagr = hist.length > 1 ? (last.revenue / first.revenue) ** (1 / (hist.length - 1)) - 1 : 0.04;
  const [a1, a2] = co.analyst_growth || [];
  const g1 = a1 ?? cagr, g2 = a2 ?? g1, tg = 0.025;
  const growth = [g1, g2, ...[1, 2, 3].map((k) => g2 + ((tg + 0.005 - g2) * k) / 3)];
  const tax = clamp(avg(last3.map((y) => y.tax_rate)) ?? 0.21, 0, 0.35);
  const debt = last.debt || 0;
  const kd = debt && last.interest ? clamp(Math.abs(last.interest) / debt, LAB.rf, LAB.rf + 0.06) : LAB.rf + 0.015;
  return {
    g: growth.map((x) => round(x * 100, 1)),
    margin: round(avg(last3.map((y) => y.margin)) * 100, 1),
    tax: round(tax * 100, 1),
    da: round(avg(last3.map((y) => y.daPct)) * 100, 1),
    capex: round(avg(last3.map((y) => y.capexPct)) * 100, 1),
    nwc: round(clamp(median(hist.map((y) => y.nwcPct)) ?? 0.05, 0, 0.3) * 100, 0),
    rf: round(LAB.rf * 100, 2), beta: round(clamp(co.beta ?? 1, 0.4, 2.5), 2), erp: round(LAB.erp * 100, 1),
    kd: round(kd * 100, 2),
    method: "gordon", tg: 2.5, multiple: round(co.ev_ebitda ?? 12, 1), mid: false,
  };
}
const round = (x, d) => Math.round(x * 10 ** d) / 10 ** d;

function load(i) {
  co = LAB.companies[i];
  hist = history();
  try { state = JSON.parse(localStorage.getItem("dcf-lab:" + co.ticker)) || defaults(); } catch { state = defaults(); }
  if (!state.g || state.g.length !== YEARS) state = defaults();
  renderStatic();
  renderInputs();
  update();
}
function save() { try { localStorage.setItem("dcf-lab:" + co.ticker, JSON.stringify(state)); } catch { /* private mode */ } }

// ---------- the model ----------
function model(s) {
  const last = hist[hist.length - 1];
  const tax = s.tax / 100, w = waccOf(s), tg = s.tg / 100;
  let prev = last.revenue;
  const rows = s.g.map((g, i) => {
    const t = i + 1, rev = prev * (1 + g / 100);
    const ebit = rev * s.margin / 100, taxes = ebit * tax, nopat = ebit - taxes;
    const da = rev * s.da / 100, capex = rev * s.capex / 100, dnwc = (rev - prev) * s.nwc / 100;
    const fcff = nopat + da - capex - dnwc;
    const factor = 1 / (1 + w.wacc) ** (t - (s.mid ? 0.5 : 0));
    prev = rev;
    return { t, g: g / 100, rev, ebit, taxes, nopat, da, capex, dnwc, fcff, factor, pv: fcff * factor };
  });
  const y5 = rows[YEARS - 1];
  const tvGordon = w.wacc > tg ? (y5.fcff * (1 + tg)) / (w.wacc - tg) : null;
  const tvMultiple = (y5.ebit + y5.da) * s.multiple;
  const tv = s.method === "gordon" ? tvGordon : tvMultiple;
  const pvTv = tv == null ? null : tv / (1 + w.wacc) ** YEARS;
  const pvSum = rows.reduce((a, r) => a + r.pv, 0);
  const ev = pvTv == null ? null : pvSum + pvTv;
  const equity = ev == null ? null : ev - (last.debt || 0) + (last.cash || 0);
  const perShare = equity == null ? null : equity / co.shares_out;
  return { rows, w, tvGordon, tvMultiple, tv, pvTv, pvSum, ev, equity, perShare,
    impliedMultiple: tvGordon == null ? null : tvGordon / (y5.ebit + y5.da),
    impliedGrowth: (tvMultiple * w.wacc - y5.fcff) / (tvMultiple + y5.fcff) };
}

function waccOf(s) {
  const last = hist[hist.length - 1], debt = last.debt || 0, equity = co.price * co.shares_out;
  const ke = s.rf / 100 + s.beta * s.erp / 100, kdAt = (s.kd / 100) * (1 - s.tax / 100), we = equity / (equity + debt);
  return { ke, kdAt, we, equity, debt, wacc: we * ke + (1 - we) * kdAt };
}

// ---------- rendering ----------
function field(key, label, unit, hint, step = 0.1) {
  return `<div class="field"><label for="in-${key}">${label}</label><div class="row">
    <input type="number" id="in-${key}" data-k="${key}" step="${step}" value="${state[key]}"><span class="unit">${unit}</span></div>
    ${hint ? `<div class="hist">${hint}</div>` : ""}</div>`;
}

function renderStatic() {
  const note = (k) => NOTES[co.ticker]?.[k] ? `<div class="company-note">${esc(NOTES[co.ticker][k])}</div>` : "";
  $("s1-explain").innerHTML = `<p>Before forecasting anything, look at what the business has actually done. These are
    ${esc(co.name)}'s last ${hist.length} fiscal years, with each line also shown as a percentage of revenue, which is
    how the forecast in Step 3 will be built.</p>${note("s1")}`;
  const cols = hist.map((y) => `<th>FY${esc(y.fy)}</th>`).join("");
  const line = (name, f, cls = "") => `<tr class="${cls}"><td>${name}</td>${hist.map((y) => `<td>${f(y)}</td>`).join("")}</tr>`;
  $("history").innerHTML = `<tr><th></th>${cols}</tr>` +
    line("Revenue", (y) => B(y.revenue)) + line("growth", (y) => P(y.growth), "sub") +
    line("EBIT (operating profit)", (y) => B(y.ebit)) + line("margin", (y) => P(y.margin), "sub") +
    line("Tax rate", (y) => P(y.tax_rate)) +
    line("D&amp;A", (y) => B(y.da)) + line("% of revenue", (y) => P(y.daPct), "sub") +
    line("Capital spending", (y) => B(y.capex)) + line("% of revenue", (y) => P(y.capexPct), "sub") +
    line("Increase in working capital", (y) => B(y.nwc_investment)) +
    line("% of revenue change", (y) => (y.nwcPct == null ? "–" : P(y.nwcPct, 0)), "sub") +
    line("Free cash flow to the firm", (y) => B(y.fcff), "total") +
    line("Debt", (y) => B(y.debt), "sub") + line("Cash", (y) => B(y.cash), "sub");
  const last = hist[hist.length - 1], first = hist[0];
  const cagr = hist.length > 1 ? (last.revenue / first.revenue) ** (1 / (hist.length - 1)) - 1 : null;
  const [a1, a2] = co.analyst_growth || [];
  $("s2-hints").innerHTML = `Track record: <b>${P(cagr)}</b> a year over FY${first.fy} to FY${last.fy}.` +
    (a1 != null ? ` Analysts expect <b>${P(a1)}</b> next fiscal year and <b>${P(a2)}</b> the year after.` : "") +
    ` Long-run economy: about <b>2 to 3%</b>.`;
  $("lab-footer").textContent = `${co.name} data as of ${co.fetched}. Educational tool, not investment advice.`;
  document.querySelectorAll(".company-note.dyn").forEach((n) => n.remove());
  for (const [k, id] of [["s4", "wacc-inputs"], ["s5", "tv-inputs"]]) {
    if (NOTES[co.ticker]?.[k]) $(id).insertAdjacentHTML("beforebegin", `<div class="company-note dyn">${esc(NOTES[co.ticker][k])}</div>`);
  }
}

function renderInputs() {
  const h3 = (f) => P(avg(hist.slice(-3).map(f)));
  const last = hist[hist.length - 1];
  $("growth-inputs").innerHTML = state.g.map((g, i) => `<div class="field"><label for="in-g${i}">Year ${i + 1}</label>
    <div class="row"><input type="number" id="in-g${i}" data-g="${i}" step="0.1" value="${g}"><span class="unit">%</span></div></div>`).join("");
  $("fcf-inputs").innerHTML =
    field("margin", "EBIT margin", "%", `3-year average ${h3((y) => y.margin)}`) +
    field("tax", "Tax rate", "%", `3-year average ${h3((y) => y.tax_rate)}`) +
    field("da", "D&amp;A, % of revenue", "%", `3-year average ${h3((y) => y.daPct)}`) +
    field("capex", "Capex, % of revenue", "%", `3-year average ${h3((y) => y.capexPct)}`) +
    field("nwc", "Working capital, % of revenue growth", "%", "Cash tied up per extra $1 of sales", 1);
  $("wacc-inputs").innerHTML =
    field("rf", "Risk-free rate (10-year Treasury)", "%", "Today's 10-year yield", 0.01) +
    field("beta", "Beta", "", `Yahoo: ${co.beta?.toFixed(2) ?? "n/a"}`, 0.01) +
    field("erp", "Equity risk premium", "%", "Commonly 4 to 6%", 0.1) +
    field("kd", "Pre-tax cost of debt", "%", last.interest && last.debt ? `Interest &divide; debt: ${P(Math.abs(last.interest) / last.debt)}` : "", 0.01);
  $("tv-inputs").innerHTML = `<div class="toggle" role="group" aria-label="Terminal value method">
      <button data-method="gordon" class="${state.method === "gordon" ? "on" : ""}">Perpetuity growth</button>
      <button data-method="multiple" class="${state.method === "multiple" ? "on" : ""}">Exit multiple</button></div>` +
    field("tg", "Long-run growth", "%", "Keep below about 3%") +
    field("multiple", "Exit EV/EBITDA multiple", "x", `Trades at ${co.ev_ebitda?.toFixed(1) ?? "n/a"}x today`) +
    `<div class="field"><label>Cash flow timing</label><div class="toggle">
      <button data-mid="0" class="${state.mid ? "" : "on"}">Year end</button>
      <button data-mid="1" class="${state.mid ? "on" : ""}">Mid-year</button></div>
      <div class="hist">Mid-year assumes cash arrives through the year</div></div>`;
}

function onInput(e) {
  const t = e.target;
  if (t.dataset.g != null) state.g[+t.dataset.g] = +t.value;
  else if (t.dataset.k) state[t.dataset.k] = +t.value;
  else return;
  save(); update();
}
function onToggle(e) {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.method) state.method = b.dataset.method;
  else if (b.dataset.mid != null) state.mid = b.dataset.mid === "1";
  else return;
  save(); renderInputs(); update();
}

function update() {
  const m = model(state), last = hist[hist.length - 1];
  const fyNext = (k) => `FY${+last.fy + k}`;
  const hdr = `<tr><th></th><th>FY${esc(last.fy)} actual</th>${m.rows.map((r) => `<th>${fyNext(r.t)}</th>`).join("")}</tr>`;
  const row = (name, base, f, cls = "") => `<tr class="${cls}"><td>${name}</td><td>${base}</td>${m.rows.map((r) => `<td class="fc">${f(r)}</td>`).join("")}</tr>`;
  $("rev-table").innerHTML = hdr + row("Revenue", B(last.revenue), (r) => B(r.rev), "total") +
    row("growth", P(hist[hist.length - 1].growth), (r) => P(r.g), "sub");
  $("fcf-table").innerHTML = hdr + row("Revenue", B(last.revenue), (r) => B(r.rev)) +
    row("EBIT", B(last.ebit), (r) => B(r.ebit)) + row("&minus; Taxes on EBIT", "", (r) => B(-r.taxes), "sub") +
    row("= NOPAT", "", (r) => B(r.nopat)) + row("+ D&amp;A", B(last.da), (r) => B(r.da), "sub") +
    row("&minus; Capital spending", B(-last.capex), (r) => B(-r.capex), "sub") +
    row("&minus; Increase in working capital", B(-last.nwc_investment), (r) => B(-r.dnwc), "sub") +
    row("Free cash flow to the firm", B(last.fcff ?? hist[hist.length - 1].fcff), (r) => B(r.fcff), "total");

  const w = m.w;
  $("wacc-out").innerHTML = `<p class="out-line">Cost of equity = ${state.rf.toFixed(2)}% + ${state.beta.toFixed(2)} &times; ${state.erp.toFixed(1)}% = <b>${P(w.ke, 2)}</b></p>
    <p class="out-line">After-tax cost of debt = ${state.kd.toFixed(2)}% &times; (1 &minus; ${state.tax.toFixed(1)}%) = <b>${P(w.kdAt, 2)}</b></p>
    <p class="out-line">Weights at market value: equity ${B(w.equity)} (${P(w.we, 0)}), debt ${B(w.debt)} (${P(1 - w.we, 0)})</p>
    <p class="out-line">WACC = <b>${P(w.wacc, 2)}</b></p>`;

  const tvWarn = state.tg / 100 >= w.wacc ? `<p class="check">Long-run growth must be below the discount rate, or the formula breaks: a company growing faster than its cost of capital forever would be worth infinity.</p>` : "";
  $("tv-out").innerHTML = tvWarn + `<p class="out-line">Perpetuity growth value: <b>${B(m.tvGordon)}</b>, which is ${m.impliedMultiple ? m.impliedMultiple.toFixed(1) + "x" : "–"} year-5 EBITDA</p>
    <p class="out-line">Exit multiple value: <b>${B(m.tvMultiple)}</b>, which implies ${P(m.impliedGrowth)} growth forever</p>
    <p class="out-line">Using <b>${state.method === "gordon" ? "perpetuity growth" : "the exit multiple"}</b>: the terminal value is ${m.ev ? P(m.pvTv / m.ev, 0) : "–"} of enterprise value.</p>`;

  const up = m.perShare / co.price - 1;
  $("bridge").innerHTML = `<table class="data">
    <tr><td>Present value of year 1 to 5 cash flows</td><td>${B(m.pvSum)}</td></tr>
    <tr><td>+ Present value of the terminal value</td><td>${B(m.pvTv)}</td></tr>
    <tr class="total"><td>= Enterprise value</td><td>${B(m.ev)}</td></tr>
    <tr><td>&minus; Debt</td><td>${B(-(last.debt || 0))}</td></tr>
    <tr><td>+ Cash</td><td>${B(last.cash || 0)}</td></tr>
    <tr class="total"><td>= Equity value</td><td>${B(m.equity)}</td></tr>
    <tr><td>&divide; Shares outstanding</td><td>${(co.shares_out / 1e9).toFixed(3)}B</td></tr>
    <tr class="total"><td>= Value per share</td><td>${m.perShare == null ? "–" : "$" + m.perShare.toFixed(2)}</td></tr></table>`;
  $("result-bar").innerHTML = `<div class="wrap"><span><span class="k">${esc(co.ticker)} your value</span><b>${m.perShare == null ? "–" : "$" + m.perShare.toFixed(0)}</b></span>
    <span><span class="k">Price</span><b>$${co.price.toFixed(0)}</b></span>
    <span><span class="k">Difference</span><b>${m.perShare == null ? "–" : signedPct(up)}</b></span>
    <span><span class="k">WACC</span>${P(w.wacc, 1)}</span><span><span class="k">Terminal share</span>${m.ev ? P(m.pvTv / m.ev, 0) : "–"}</span></div>`;
  renderSensitivity();
  renderChecks(m);
}

function renderSensitivity() {
  const base = model(state).w.wacc;
  const rates = [-0.01, -0.005, 0, 0.005, 0.01].map((d) => base + d);
  const gordon = state.method === "gordon";
  const cols = gordon ? [-1, -0.5, 0, 0.5, 1].map((d) => state.tg + d) : [-2, -1, 0, 1, 2].map((d) => state.multiple + d);
  const valueAt = (rate, c) => {
    // Shift the cost of equity so WACC lands on `rate`, keeping every other input
    const w = waccOf(state), s = { ...state, erp: state.erp + ((rate - w.wacc) / w.we / state.beta) * 100 };
    if (gordon) s.tg = c; else s.multiple = c;
    return model(s).perShare;
  };
  $("sens").innerHTML = `<tr><th>WACC</th>${cols.map((c) => `<th>${gordon ? c.toFixed(1) + "%" : c.toFixed(1) + "x"}</th>`).join("")}</tr>` +
    rates.map((r, i) => `<tr><td>${P(r, 1)}</td>${cols.map((c, j) => {
      const v = valueAt(r, c), center = i === 2 && j === 2;
      if (v == null || !isFinite(v)) return `<td class="cell">n/a</td>`;
      const above = v >= co.price;
      return `<td class="cell" style="background:${above ? "var(--up-bg)" : "var(--down-bg)"};${center ? "outline:2px solid var(--ink);font-weight:700" : ""}">$${v.toFixed(0)}</td>`;
    }).join("")}</tr>`).join("");
}

function renderChecks(m) {
  const notes = [], last3 = hist.slice(-3);
  const histMargin = avg(last3.map((y) => y.margin)) * 100;
  if (m.perShare != null) {
    const up = m.perShare / co.price - 1;
    notes.push(`Your model values ${esc(co.name)} at <b>$${m.perShare.toFixed(2)}</b>, ${Math.abs(up * 100).toFixed(0)}% ${up >= 0 ? "above" : "below"} today's $${co.price.toFixed(2)}.
      ${Math.abs(up) < 0.15 ? "That is close to the market: your assumptions look roughly like what investors are paying for." :
        up < 0 ? "To reach today's price you would need faster growth, higher margins, a lower discount rate, or a higher terminal value. Which of those do you find believable?" :
        "The market is more cautious than you. Is there a risk your model leaves out?"}`);
  }
  if (co.letter_model) notes.push(`The letter's automated model (a ${co.letter_model.years}-year version that holds the free cash flow margin flat) gets <b>$${co.letter_model.per_share.toFixed(0)}</b> at a ${P(co.letter_model.wacc, 1)} WACC. Comparing the two shows how much the answer depends on method, not just inputs.`);
  if (m.ev && m.pvTv / m.ev > 0.75) notes.push(`The terminal value is ${P(m.pvTv / m.ev, 0)} of the total, so most of your answer rests on the years after 2030. That is common for steady companies, but it means the long-run assumptions deserve the most thought.`);
  if (Math.abs(state.margin - histMargin) > 5) notes.push(`Your EBIT margin (${state.margin.toFixed(1)}%) is well away from the recent average (${histMargin.toFixed(1)}%). That can be right, but you should be able to say why margins will change.`);
  if (state.tg > 3) notes.push(`A long-run growth rate above 3% assumes the company outgrows the economy forever. Most analysts stay at 2 to 3%.`);
  if (m.impliedMultiple && Math.abs(m.impliedMultiple - (co.ev_ebitda || m.impliedMultiple)) / (co.ev_ebitda || 1) > 0.4)
    notes.push(`Your perpetuity growth value works out to ${m.impliedMultiple.toFixed(1)}x EBITDA, far from the ${co.ev_ebitda.toFixed(1)}x the stock trades at today. When the two terminal methods disagree this much, one of the assumptions behind them is probably off.`);
  $("check").innerHTML = notes.map((n) => `<p class="check">${n}</p>`).join("");
}

// ---------- Excel export with live formulas ----------
function exportXlsx() {
  XLSX.writeFile(buildWorkbook(), `${co.ticker}_DCF.xlsx`);
}

function buildWorkbook() {
  const ws = {}, M = 1e6, last = hist[hist.length - 1], s = state;
  const set = (addr, v, z) => {
    ws[addr] = typeof v === "object" && v !== null ? { t: "n", f: v.f } : { t: typeof v === "number" ? "n" : "s", v };
    if (z) ws[addr].z = z;
  };
  const pct = "0.0%", num = "#,##0", usd = "$#,##0.00", mult = "0.0\"x\"";
  set("A1", `${co.name} (${co.ticker}): five-year DCF`);
  set("A2", "US$ millions except per share. Inputs: B4:B27 and the growth rates in row 31. Everything else is a formula; change an input and the model updates.");
  const inputs = [
    ["A4", "Share price", co.price, usd], ["A5", "Shares outstanding (millions)", co.shares_out / M, num],
    ["A6", `Total debt, FY${last.fy}`, (last.debt || 0) / M, num], ["A7", `Cash, FY${last.fy}`, (last.cash || 0) / M, num],
    ["A9", "Risk-free rate", s.rf / 100, "0.00%"], ["A10", "Beta", s.beta, "0.00"], ["A11", "Equity risk premium", s.erp / 100, pct],
    ["A13", "Pre-tax cost of debt", s.kd / 100, "0.00%"], ["A14", "Tax rate", s.tax / 100, pct],
    ["A20", "EBIT margin", s.margin / 100, pct], ["A21", "D&A, % of revenue", s.da / 100, pct],
    ["A22", "Capex, % of revenue", s.capex / 100, pct], ["A23", "Working capital, % of revenue growth", s.nwc / 100, pct],
    ["A24", "Long-run growth", s.tg / 100, pct], ["A25", "Exit EV/EBITDA multiple", s.multiple, mult],
    ["A26", "Terminal method (1 = perpetuity growth, 2 = exit multiple)", s.method === "gordon" ? 1 : 2, "0"],
    ["A27", "Mid-year discounting (1 = yes, 0 = no)", s.mid ? 1 : 0, "0"],
  ];
  for (const [a, label, v, z] of inputs) { set(a, label); set("B" + a.slice(1), v, z); }
  set("A12", "Cost of equity (CAPM)"); set("B12", { f: "B9+B10*B11" }, "0.00%");
  set("A15", "After-tax cost of debt"); set("B15", { f: "B13*(1-B14)" }, "0.00%");
  set("A16", "Market value of equity"); set("B16", { f: "B4*B5" }, num);
  set("A17", "Equity weight"); set("B17", { f: "B16/(B16+B6)" }, pct);
  set("A18", "WACC"); set("B18", { f: "B17*B12+(1-B17)*B15" }, "0.00%");

  const cols = ["C", "D", "E", "F", "G", "H"];
  set("A30", "Fiscal year"); set("C30", `FY${last.fy} actual`);
  set("A31", "Revenue growth"); set("A32", "Revenue"); set("A33", "EBIT"); set("A34", "Taxes on EBIT"); set("A35", "NOPAT");
  set("A36", "D&A"); set("A37", "Capital spending"); set("A38", "Increase in working capital"); set("A39", "Free cash flow to the firm");
  set("A40", "Year"); set("A41", "Discount factor"); set("A42", "Present value");
  set("C32", last.revenue / M, num); set("C33", last.ebit / M, num);
  for (let i = 1; i <= YEARS; i++) {
    const c = cols[i], p = cols[i - 1];
    set(c + "30", `FY${+last.fy + i}`);
    set(c + "31", s.g[i - 1] / 100, pct);
    set(c + "32", { f: `${p}32*(1+${c}31)` }, num);
    set(c + "33", { f: `${c}32*$B$20` }, num);
    set(c + "34", { f: `${c}33*$B$14` }, num);
    set(c + "35", { f: `${c}33-${c}34` }, num);
    set(c + "36", { f: `${c}32*$B$21` }, num);
    set(c + "37", { f: `${c}32*$B$22` }, num);
    set(c + "38", { f: `(${c}32-${p}32)*$B$23` }, num);
    set(c + "39", { f: `${c}35+${c}36-${c}37-${c}38` }, num);
    set(c + "40", i, "0");
    set(c + "41", { f: `1/(1+$B$18)^(${c}40-0.5*$B$27)` }, "0.0000");
    set(c + "42", { f: `${c}39*${c}41` }, num);
  }
  const rows = [
    ["A44", "Sum of present values, years 1 to 5", "SUM(D42:H42)", num],
    ["A45", "Terminal value, perpetuity growth", "H39*(1+B24)/(B18-B24)", num],
    ["A46", "Terminal value, exit multiple", "(H33+H36)*B25", num],
    ["A47", "Terminal value used", "IF(B26=1,B45,B46)", num],
    ["A48", "Present value of terminal value", "B47/(1+B18)^5", num],
    ["A49", "Enterprise value", "B44+B48", num],
    ["A50", "Less debt, plus cash: equity value", "B49-B6+B7", num],
    ["A51", "Value per share", "B50/B5", usd],
    ["A52", "Versus share price", "B51/B4-1", pct],
    ["A53", "Terminal value share of enterprise value", "B48/B49", pct],
  ];
  for (const [a, label, f, z] of rows) { set(a, label); set("B" + a.slice(1), { f }, z); }
  ws["!ref"] = "A1:H53";
  ws["!cols"] = [{ wch: 52 }, { wch: 14 }, { wch: 14 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }];

  // A second sheet with the historical statements the assumptions came from
  const hs = XLSX.utils.aoa_to_sheet([
    ["US$ millions", ...hist.map((y) => `FY${y.fy}`)],
    ...[["Revenue", "revenue"], ["EBIT", "ebit"], ["D&A", "da"], ["Capital spending", "capex"],
      ["Increase in working capital", "nwc_investment"], ["Interest expense", "interest"], ["Total debt", "debt"], ["Cash", "cash"]]
      .map(([n, k]) => [n, ...hist.map((y) => (y[k] == null ? null : y[k] / M))]),
    ["Tax rate", ...hist.map((y) => y.tax_rate)],
  ]);
  hs["!cols"] = [{ wch: 30 }, ...hist.map(() => ({ wch: 12 }))];
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "DCF");
  XLSX.utils.book_append_sheet(wb, hs, "History");
  return wb;
}
