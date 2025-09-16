// invest-analyzer.js  — full client logic with "Fetch data" prefill + existing submit/status flow

// ==== API endpoints (change to your app URLs) ====
const API_SUBMIT  = "https://invest-analyzer-func.azurewebsites.net/api/submit";
const API_STATUS  = "https://invest-analyzer-func.azurewebsites.net/api/status?id=";
// If your Azure Function uses authLevel=function, append ?code=YOUR_FUNC_KEY
const API_PREFILL = "https://invest-analyzer-func.azurewebsites.net/api/prefill";

// ==== formatting helpers ====
const fmtMoney = (v) => (isFinite(v) ? "$" + Number(v).toLocaleString() : "—");
const fmtPct   = (v, d = 1) => (isFinite(v) ? (Number(v) * 100).toFixed(d) + "%" : "—");

// ==== fetch helper that surfaces server error text ====
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  const text = await r.text();
  try { return JSON.parse(text); }
  catch {
    const snippet = text ? text.slice(0, 300) : "(empty body)";
    throw new Error(`Bad response ${r.status} ${r.statusText}: ${snippet}`);
  }
}

// ==== form helpers ====
function getFormObj(form) {
  const obj = Object.fromEntries(new FormData(form).entries());
  // coerce numeric fields
  ["dpPct","rate","term","vacancyPct","mgmtPct","rehab","hoa","insurance","taxes","holdYears"]
    .forEach(k => obj[k] = Number(obj[k] ?? 0));
  // single-line address for lookups
  obj.addressOneLine = [obj.address, obj.unit, obj.city, obj.state, obj.zip]
    .filter(Boolean).join(", ");
  return obj;
}
function setIfEmpty(form, name, val) {
  const el = form.querySelector(`[name="${name}"]`);
  if (!el) return;
  if (el.value === "" || el.value == null) el.value = (val ?? "");
}
function setVal(form, name, val) {
  const el = form.querySelector(`[name="${name}"]`);
  if (el) el.value = (val ?? "");
}

// ==== main ====
document.addEventListener("DOMContentLoaded", () => {
  // ---------- Submit handler (Analyze) ----------
  const form = document.getElementById("investForm");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const elStatus = document.getElementById("submitStatus");
      const data = getFormObj(form);

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

  // ---------- Prefill handler (Fetch data) ----------
  const btnFetch = document.getElementById("btnFetch");
  const fetchStatus = document.getElementById("fetchStatus");
  if (btnFetch && form) {
    btnFetch.addEventListener("click", async () => {
      fetchStatus.textContent = "Fetching…";
      try {
        const payload = getFormObj(form);
        const res = await fetchJSON(API_PREFILL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: payload.addressOneLine })
        });
        if (!res.ok) throw new Error(res.error || "Lookup failed");

        const est   = res.estimates || {};
        const parts = res.address_parts || {};

        // backfill address parts if user only typed street
        setIfEmpty(form, "address", parts.street);
        setIfEmpty(form, "city",    parts.city);
        setIfEmpty(form, "state",   parts.state);
        setIfEmpty(form, "zip",     parts.zip);

        // costs (only fill if currently empty so user can override later)
        if (est.hoa_monthly != null)       setIfEmpty(form, "hoa", est.hoa_monthly);
        if (est.tax_monthly != null)       setIfEmpty(form, "taxes", est.tax_monthly);
        if (est.insurance_monthly != null) setIfEmpty(form, "insurance", est.insurance_monthly);

        // Optional: if your backend returns price & rent, inject fields if not present
        if (est.suggested_price != null) {
          if (!form.querySelector('[name="price"]')) {
            const priceInput = document.createElement("input");
            priceInput.name = "price";
            priceInput.type = "number";
            priceInput.placeholder = "Purchase price ($)";
            priceInput.min = 0;
            priceInput.value = est.suggested_price;
            // insert right after the Street Address label
            const streetLabel = form.querySelector('label > input[name="address"]').closest('label');
            streetLabel.after(priceInput);
          } else {
            setIfEmpty(form, "price", est.suggested_price);
          }
        }
        if (est.rent_monthly != null) {
          if (!form.querySelector('[name="rent"]')) {
            const rentInput = document.createElement("input");
            rentInput.name = "rent";
            rentInput.type = "number";
            rentInput.placeholder = "Rent ($/mo)";
            rentInput.min = 0;
            rentInput.value = est.rent_monthly;
            // add after the HOA/Insurance/Taxes grid
            const grids = form.querySelectorAll('.grid-3');
            const lastGrid = grids[grids.length - 1];
            lastGrid.after(rentInput);
          } else {
            setIfEmpty(form, "rent", est.rent_monthly);
          }
        }

        fetchStatus.textContent = res.note || "Filled estimates. Review & adjust, then click Analyze.";
      } catch (err) {
        console.error(err);
        fetchStatus.textContent = "Couldn’t fetch data (you can fill manually).";
      }
    });
  }

  // ---------- Status page poller ----------
  const statusEl = document.getElementById("status");
  if (statusEl) {
    const summaryEl   = document.getElementById("summary");
    const estimatesEl = document.getElementById("estimates");
    const metricsEl   = document.getElementById("metricsWrap");
    const errorEl     = document.getElementById("error");

    // helper: build {label, cls} and render badge
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
      if (!id) { if (errorEl) errorEl.textContent = "Missing analysis id."; return; }

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
                  <span class="small">Cap Rate = NOI ÷ Purchase Price.</span>
                </li>
                <li><strong>Cash Flow/mo:</strong> ${fmtMoney(m.cash_flow_month)}</li>
                <li><strong>NOI/mo:</strong> ${fmtMoney(m.noi_month)}</li>
                <li><strong>P&amp;I/mo:</strong> ${fmtMoney(m.pi_month)}</li>
                <li><strong>Cash-on-Cash (CoC):</strong> ${fmtPct(m.coc || 0, 2)}<br>
                  <span class="small">CoC = Annual Cash Flow ÷ Total Cash Invested.</span>
                </li>
                <li><strong>IRR (${m.irr_years ?? "—"} yrs):</strong> ${
                  isFinite(m.irr) ? (m.irr*100).toFixed(2) + "%" : "—"
                }<br>
                  <span class="small">IRR includes cash flows and sale with payoff & selling costs.</span>
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