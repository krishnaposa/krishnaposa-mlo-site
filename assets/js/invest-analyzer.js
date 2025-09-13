// invest-analyzer.js
const API_SUBMIT = "https://invest-analyzer-func.azurewebsites.net/api/submit";
const API_STATUS = "https://invest-analyzer-func.azurewebsites.net/api/status?id=";

const fmtMoney = (v) => (isFinite(v) ? "$" + Number(v).toLocaleString() : "—");
const fmtPct   = (v, d=1) => (isFinite(v) ? (Number(v)*100).toFixed(d) + "%" : "—");

// Safer fetch helper: always read text first, then parse JSON for clearer errors
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
  // ---------- Submit handler (invest.html) ----------
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

        // Redirect to status.html (same directory as current page)
        const statusUrl = new URL("status.html", location.href);
        statusUrl.searchParams.set("id", j.id);
        location.href = statusUrl.toString();
      } catch (err) {
        elStatus.textContent = "Error: " + err.message;
      }
    });
  }

  // ---------- Status poller (status.html) ----------
  const statusEl   = document.getElementById("status");
  if (statusEl) {
    const summaryEl   = document.getElementById("summary");
    const estimatesEl = document.getElementById("estimates");
    const metricsEl   = document.getElementById("metricsWrap");
    const errorEl     = document.getElementById("error");

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
        const label = (a.status || (a.runtimeStatus ? String(a.runtimeStatus).toLowerCase() : "unknown"));
        statusEl.textContent = label.toUpperCase();

        if (a.error && errorEl) errorEl.textContent = a.error;

        if (a.status === "done") {
          // reveal previously hidden sections (use classList, not style.display)
          if (summaryEl)   summaryEl.classList.remove("hidden");
          if (estimatesEl) estimatesEl.classList.remove("hidden");
          if (metricsEl)   metricsEl.classList.remove("hidden");

          // summary
          const verdictEl = document.getElementById("verdict");
          const reasonsEl = document.getElementById("reasons");
          if (verdictEl) verdictEl.textContent = "Verdict: " + (a.verdict || "").toUpperCase();
          if (reasonsEl) reasonsEl.textContent = a.reasons || "";

          // estimates
          const e = a.estimates || {};
          if (estimatesEl) {
            estimatesEl.innerHTML = `
              <h4>Key Estimates</h4>
              <ul class="results-list">
                <li><strong>Rent (est):</strong> ${fmtMoney(e.rent_est)}</li>
                <li><strong>Price (est):</strong> ${fmtMoney(e.price_est)}</li>
                <li><strong>Taxes/mo:</strong> ${fmtMoney(e.taxes_month)}</li>
                <li><strong>Insurance/mo:</strong> ${fmtMoney(e.ins_month)}</li>
                <li><strong>HOA/mo:</strong> ${fmtMoney(e.hoa_month)}</li>
                <li><strong>Appreciation (HPI):</strong> ${
                  isFinite(e.hpi_growth) ? (e.hpi_growth*100).toFixed(2) + "%" : "—"
                }</li>
              </ul>`;
          }

          // metrics
          const m = a.metrics || {};
          if (metricsEl) {
            metricsEl.innerHTML = `
              <h4>Metrics</h4>
              <ul class="results-list">
                <li><strong>Cap Rate:</strong> ${fmtPct(m.cap_rate || 0, 2)}</li>
                <li><strong>Cash Flow/mo:</strong> ${fmtMoney(m.cash_flow_month)}</li>
                <li><strong>NOI/mo:</strong> ${fmtMoney(m.noi_month)}</li>
                <li><strong>P&amp;I/mo:</strong> ${fmtMoney(m.pi_month)}</li>
                <li><strong>Cash-on-Cash:</strong> ${fmtPct(m.coc || 0, 2)}</li>
                <li><strong>IRR (years):</strong> ${m.irr_years ?? "—"} | <strong>IRR:</strong> ${
                  isFinite(m.irr) ? (m.irr*100).toFixed(2) + "%" : "—"
                }</li>
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