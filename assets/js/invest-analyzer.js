// invest-analyzer.js
const API_SUBMIT = "https://invest-analyzer-func.azurewebsites.net/api/submit";
const API_STATUS = "https://invest-analyzer-func.azurewebsites.net/api/status?id=";

const fmtMoney = (v) => (isFinite(v) ? "$" + Number(v).toLocaleString() : "—");
const fmtPct   = (v, d=1) => (isFinite(v) ? (Number(v)*100).toFixed(d) + "%" : "—");

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

    function deriveSources(a, e) {
      const pulls = a.pulls || {};
      const raw = (pulls.raw || {});
      const dbg = (pulls.debug || {});
      const has = (obj, path) => path.split(".").reduce((p,k)=> (p && p[k]!==undefined ? p[k] : undefined), obj);

      const rentcastRentOK  = !!has(dbg, "rentcast_rent.ok");
      const rentcastValueOK = !!has(dbg, "rentcast_value.ok");
      const zillowOK        = !!has(dbg, "zillow.ok") && (has(dbg, "zillow.hoa") > 0);

      return {
        rent_est: (rentcastRentOK) ? "RentCast" : (e.rent_est > 0 ? "Heuristic" : "Unknown"),
        price_est: (rentcastValueOK) ? "RentCast AVM" : (e.price_est > 0 ? "Heuristic" : "Unknown"),
        taxes_month: (e.price_est > 0) ? "Heuristic (state avg)" : "Unknown",
        ins_month: (e.price_est > 0) ? "Heuristic (state baseline)" : "Unknown",
        hoa_month: (zillowOK && e.hoa_month > 0) ? "Zillow (RapidAPI)" :
                   (e.hoa_month > 0 ? "User-supplied" : "Not available"),
        hpi_growth: "FHFA/FRED (state HPI)"
      };
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
          if (summaryEl)   summaryEl.classList.remove("hidden");
          if (estimatesEl) estimatesEl.classList.remove("hidden");
          if (metricsEl)   metricsEl.classList.remove("hidden");

          const verdictEl = document.getElementById("verdict");
          const reasonsEl = document.getElementById("reasons");
          if (verdictEl) verdictEl.textContent = "Verdict: " + (a.verdict || "").toUpperCase();
          if (reasonsEl) reasonsEl.textContent = a.reasons || "";

          const e = a.estimates || {};
          const sources = deriveSources(a, e);
          if (estimatesEl) {
            estimatesEl.innerHTML = `
              <h4>Key Estimates</h4>
              <ul class="results-list">
                <li><strong>Rent (est):</strong> ${fmtMoney(e.rent_est)} <span class="src-badge">${sources.rent_est}</span></li>
                <li><strong>Price (est):</strong> ${fmtMoney(e.price_est)} <span class="src-badge">${sources.price_est}</span></li>
                <li><strong>Taxes/mo:</strong> ${fmtMoney(e.taxes_month)} <span class="src-badge">${sources.taxes_month}</span></li>
                <li><strong>Insurance/mo:</strong> ${fmtMoney(e.ins_month)} <span class="src-badge">${sources.ins_month}</span></li>
                <li><strong>HOA/mo:</strong> ${fmtMoney(e.hoa_month)} <span class="src-badge">${sources.hoa_month}</span></li>
                <li><strong>Appreciation (HPI):</strong> ${isFinite(e.hpi_growth) ? (e.hpi_growth*100).toFixed(2) + "%" : "—"} <span class="src-badge">${sources.hpi_growth}</span></li>
              </ul>`;
          }

          const m = a.metrics || {};
          if (metricsEl) {
            metricsEl.innerHTML = `
              <h4>Metrics</h4>
              <ul class="results-list">
                <li><strong>Cap Rate:</strong> ${fmtPct(m.cap_rate || 0, 2)}<br>
                  <span class="small">Cap Rate is NOI ÷ Purchase Price. It measures unleveraged return if you bought in cash.</span>
                </li>
                <li><strong>Cash Flow/mo:</strong> ${fmtMoney(m.cash_flow_month)}</li>
                <li><strong>NOI/mo:</strong> ${fmtMoney(m.noi_month)}</li>
                <li><strong>P&amp;I/mo:</strong> ${fmtMoney(m.pi_month)}</li>
                <li><strong>Cash-on-Cash (CoC):</strong> ${fmtPct(m.coc || 0, 2)}<br>
                  <span class="small">CoC is annual pre-tax cash flow ÷ total cash invested. It measures actual return on money you put in.</span>
                </li>
                <li><strong>IRR (${m.irr_years ?? "—"} yrs):</strong> ${isFinite(m.irr) ? (m.irr*100).toFixed(2) + "%" : "—"}<br>
                  <span class="small">IRR is the annualized return including future sale proceeds. It accounts for both cash flow and appreciation.</span>
                </li>
              </ul>
              <details style="margin-top:.5rem">
                <summary class="small">Raw JSON</summary>
                <pre class="metrics">${JSON.stringify({estimates:a.estimates, metrics:a.metrics}, null, 2)}</pre>
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