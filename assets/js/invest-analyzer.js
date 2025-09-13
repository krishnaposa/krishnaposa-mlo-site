// invest-analyzer.js
const API_SUBMIT = "https://invest-analyzer-func.azurewebsites.net/api/submit";
const API_STATUS = "https://invest-analyzer-func.azurewebsites.net/api/status?id=";

const fmtMoney = (v) => (isFinite(v) ? "$" + Number(v).toLocaleString() : "—");
const fmtPct   = (v, d=1) => (isFinite(v) ? (Number(v)*100).toFixed(d) + "%" : "—");

// safer fetch -> show server text in errors
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  const text = await r.text();
  try { return JSON.parse(text); }
  catch {
    const snippet = text ? text.slice(0, 300) : "(empty body)";
    throw new Error(`Bad response ${r.status} ${r.statusText}: ${snippet}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // ---------- Submit handler ----------
  const form = document.getElementById("investForm");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const elStatus = document.getElementById("submitStatus");
      const data = Object.fromEntries(new FormData(form).entries());
      ["dpPct","rate","term","vacancyPct","mgmtPct","rehab","hoa","insurance","taxes","holdYears"]
        .forEach(k => data[k] = Number(data[k] ?? 0));

      elStatus.textContent = "Submitting…";
      try {
        const j = await fetchJSON(API_SUBMIT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        if (!j.ok) throw new Error(j.error || "Submission failed");

        const statusUrl = new URL("status.html", location.href);
        statusUrl.searchParams.set("id", j.id);
        location.href = statusUrl.toString();
      } catch (err) {
        elStatus.textContent = "Error: " + err.message;
      }
    });
  }

  // ---------- Status poller ----------
  const statusEl   = document.getElementById("status");
  if (statusEl) {
    const summaryEl   = document.getElementById("summary");
    const estimatesEl = document.getElementById("estimates");
    const metricsEl   = document.getElementById("metricsWrap");
    const errorEl     = document.getElementById("error");

    // helper: build {label, cls}
    const src = (label, cls) => ({ label, cls });
    const badgeHTML = (s) => `<span class="src-badge ${s.cls}">${s.label}</span>`;

    function deriveSources(a, e) {
      const pulls = a.pulls || {};
      const raw = pulls.raw || {};
      const dbg = pulls.debug || {};
      const has = (obj, path) => path.split(".").reduce((p,k)=> (p && p[k]!==undefined ? p[k] : undefined), obj);

      const rentcastRentOK  = !!has(dbg, "rentcast_rent.ok")  || Object.keys(raw.rentcast_rent  || {}).length > 0;
      const rentcastValueOK = !!has(dbg, "rentcast_value.ok") || Object.keys(raw.rentcast_value || {}).length > 0;
      const zillowHOAOK     = !!has(dbg, "zillow.ok") && (has(dbg, "zillow.hoa") > 0);

      // decide labels
      const rent_est =
        rentcastRentOK ? src("RentCast", "api")
        : (e.rent_est > 0 ? src("Estimated (from price)", "heuristic")
        : src("Unknown", "na"));

      const price_est =
        rentcastValueOK ? src("RentCast AVM", "api")
        : (e.price_est > 0 ? src("Estimated (from rent)", "heuristic")
        : src("Unknown", "na"));

      const taxes_month =
        (e.price_est > 0) ? src("Estimated (State Avg)", "heuristic")
        : src("Unknown", "na");

      const ins_month =
        (e.price_est > 0) ? src("Estimated (State Baseline)", "heuristic")
        : src("Unknown", "na");

      let hoa_month = src("N/A", "na");
      if (zillowHOAOK && e.hoa_month > 0) hoa_month = src("Zillow (RapidAPI)", "api");
      else if (e.hoa_month > 0)          hoa_month = src("User-supplied", "user");

      const hpi_growth = src("FHFA/FRED (State HPI)", "api");

      return { rent_est, price_est, taxes_month, ins_month, hoa_month, hpi_growth };
    }

    async function tick() {
      const id = new URLSearchParams(location.search).get("id");
      if (!id) {
        if (errorEl) errorEl.textContent = "Missing analysis id.";
        return;
      }
      try {
        const j = await fetchJSON(API_STATUS + encodeURIComponent(id));
        if (!j.ok) throw new Error(j.error || "Not found");

        const a = j.analysis || {};
        statusEl.textContent = (a.status || "unknown").toUpperCase();
        if (a.error && errorEl) errorEl.textContent = a.error;

        if (a.status === "done") {
          summaryEl?.classList.remove("hidden");
          estimatesEl?.classList.remove("hidden");
          metricsEl?.classList.remove("hidden");

          // summary
          const verdictEl = document.getElementById("verdict");
          const reasonsEl = document.getElementById("reasons");
          if (verdictEl) verdictEl.textContent = "Verdict: " + (a.verdict || "").toUpperCase();
          if (reasonsEl) reasonsEl.textContent = a.reasons || "";

          // estimates + provenance
          const e = a.estimates || {};
          const s = deriveSources(a, e);
          if (estimatesEl) {
            estimatesEl.innerHTML = `
              <h4>Key Estimates</h4>
              <ul class="results-list">
                <li><strong>Rent (est):</strong> ${fmtMoney(e.rent_est)} ${badgeHTML(s.rent_est)}</li>
                <li><strong>Price (est):</strong> ${fmtMoney(e.price_est)} ${badgeHTML(s.price_est)}</li>
                <li><strong>Taxes/mo:</strong> ${fmtMoney(e.taxes_month)} ${badgeHTML(s.taxes_month)}</li>
                <li><strong>Insurance/mo:</strong> ${fmtMoney(e.ins_month)} ${badgeHTML(s.ins_month)}</li>
                <li><strong>HOA/mo:</strong> ${fmtMoney(e.hoa_month)} ${badgeHTML(s.hoa_month)}</li>
                <li><strong>Appreciation (HPI):</strong> ${
                  isFinite(e.hpi_growth) ? (e.hpi_growth*100).toFixed(2) + "%" : "—"
                } ${badgeHTML(s.hpi_growth)}</li>
              </ul>
              <div class="results-legend">
                <span class="src-badge api">API</span> live provider data
                <span class="src-badge heuristic">Estimated</span> rule-of-thumb / state averages
                <span class="src-badge user">User</span> value you entered
                <span class="src-badge na">N/A</span> not available
              </div>`;
          }

          // metrics + explanations
          const m = a.metrics || {};
          if (metricsEl) {
            metricsEl.innerHTML = `
              <h4>Metrics</h4>
              <ul class="results-list">
                <li><strong>Cap Rate:</strong> ${fmtPct(m.cap_rate || 0, 2)}<br>
                  <span class="small">Cap Rate = NOI ÷ Purchase Price (what a cash buyer might earn, ignoring financing).</span>
                </li>
                <li><strong>Cash Flow/mo:</strong> ${fmtMoney(m.cash_flow_month)}</li>
                <li><strong>NOI/mo:</strong> ${fmtMoney(m.noi_month)}</li>
                <li><strong>P&amp;I/mo:</strong> ${fmtMoney(m.pi_month)}</li>
                <li><strong>Cash-on-Cash (CoC):</strong> ${fmtPct(m.coc || 0, 2)}<br>
                  <span class="small">CoC = Annual Cash Flow ÷ Total Cash Invested (down payment + rehab + closing).</span>
                </li>
                <li><strong>IRR (${m.irr_years ?? "—"} yrs):</strong> ${
                  isFinite(m.irr) ? (m.irr*100).toFixed(2) + "%" : "—"
                }<br>
                  <span class="small">IRR = annualized total return (cash flow + sale), net of selling costs and remaining loan payoff.</span>
                </li>
              </ul>
              <details style="margin-top:.5rem">
                <summary class="small">Raw JSON</summary>
                <pre class="metrics">${JSON.stringify({estimates:a.estimates, metrics:a.metrics, pulls:a.pulls}, null, 2)}</pre>
              </details>`;
          }
        }
      } catch (err) {
        if (errorEl) errorEl.textContent = err.message;
      }
    }

    tick();
    setInterval(tick, 2000);
  }
});