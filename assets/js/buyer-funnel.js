/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Apps Script submit (JSON)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // ==== YOUR APPS SCRIPT WEB APP (Deploy > New deployment > type 'Web app') ====
  // Must allow Anyone with the link (or Anyone within domain) and return JSON.
  const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbxVkjSelQjFJbQc5zNAD9m8soIyPqrZ9ICCq06TmK8lT5evRB0wmLV4mkJ6sSmpbpfG/exec';

  // ---------- tiny DOM helper ----------
  const $ = (sel) => document.querySelector(sel);

  // ---------- booking links ----------
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => { const el = $(q); if (el) el.href = BOOKING_URL; });

  // ---------- realtor co-brand ----------
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    const set = (q, v, prop="textContent") => { const el=$(q); if (el) el[prop]=v; };
    set("#agentName", data.name || "No agent added");
    set("#agentFirm", data.firm || "You can add one above");
    set("#agentAvatar", data.logo || "", "src");
    set("#h_agentName", data.name || "", "value");
    set("#h_agentEmail", data.email || "", "value");
  }
  $("#saveAgent")?.addEventListener("click", () => {
    const payload = {
      name: $("#agent_name")?.value.trim() || "",
      firm: $("#agent_firm")?.value.trim() || "",
      email: $("#agent_email")?.value.trim() || "",
      logo: $("#agent_logo")?.value.trim() || ""
    };
    localStorage.setItem("agent", JSON.stringify(payload));
    drawAgent();
  });
  drawAgent();

  // ---------- quick qualify calculator ----------
  $("#estimateBtn")?.addEventListener("click", () => {
    const price = num($("#price")?.value);
    const downInput = ($("#down")?.value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = ($("#rate")?.value || cfg.defaultRatePct);
    const ratePct = (rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));
    const zip = ($("#zip")?.value || "").trim();
    const program = $("#program")?.value || "conventional";
    const income = num($("#income")?.value);
    const debts = num($("#debts")?.value || 0);

    if (!price || !income) { const m=$("#formMsg"); if (m) m.textContent = "Please complete price and income (and down payment if available)."; return; }
    const m=$("#formMsg"); if (m) m.textContent = "";

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI") && ($("#pAndI").textContent = fmt(res.pAndI));
    $("#taxes") && ($("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi));
    $("#totalPay") && ($("#totalPay").textContent = fmt(res.total));
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "grid");

    const dtiEl = $("#dtiLine");
    if (dtiEl) {
      dtiEl.style.display = "";
      dtiEl.innerHTML = `Estimated DTI: <strong>${(dti * 100).toFixed(1)}%</strong>. Many programs prefer under 43 percent.`;
    }

    const pmiLine = $("#pmiLine");
    if (pmiLine) {
      if (program === "conventional" && res.ltv > 0.80) {
        pmiLine.style.display = "";
        pmiLine.textContent = "Mortgage insurance estimated due to down payment under 20 percent. This can drop as LTV improves.";
      } else {
        pmiLine.style.display = "none";
      }
    }

    // pass to hidden fields + persist
    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI") && ($("#h_estDTI").value = `${(dti * 100).toFixed(1)}%`);
    localStorage.setItem("lastEstimate", JSON.stringify({
      price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1)
    }));

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine") && ($("#dtiLine").style.display = "none");
    $("#pmiLine") && ($("#pmiLine").style.display = "none");
    $("#formMsg") && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // ---------- prefill + UTM ----------
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price")) $("#price").value = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate")) $("#rate").value = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch(_) {}
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");
    $("#h_utm") && ($("#h_utm").value = utm);
  })();

  // ---------- helper: fetch with timeout ----------
  async function postJSON(url, data, { timeoutMs = 12000 } = {}) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
        signal: ctrl.signal,
        mode: "cors",
        credentials: "omit"
      });
      let json = null;
      try { json = await res.json(); } catch(_) {}
      return { ok: res.ok, status: res.status, json };
    } finally { clearTimeout(t); }
  }

  // ---------- submit to Apps Script ----------
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp"); // honeypot

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    // Build payload (tolerant of missing fields)
    const payload = {
      fullName:   $("#fullName")?.value.trim() || "",
      email:      $("#email")?.value.trim() || "",
      phone:      $("#phone")?.value.trim() || "",
      timeline:   $("#timeline")?.value || "",
      occupancy:  $("#occupancy")?.value || "",
      source:     $("#source")?.value || "",
      estPrice:   $("#estPrice")?.value.trim() || "",
      estDown:    $("#estDown")?.value.trim() || "",
      employment: $("#employment")?.value || "",
      coBorrower: $("#coBorrower")?.value || "",
      notes:      $("#notes")?.value.trim() || "",
      // hidden/derived (send if present)
      estMonthly: $("#h_estMonthly")?.value || "",
      estDTI:     $("#h_estDTI")?.value || "",
      agentName:  $("#h_agentName")?.value || "",
      agentEmail: $("#h_agentEmail")?.value || "",
      utm:        $("#h_utm")?.value || "",
      // meta
      page: location.href,
      ts: new Date().toISOString()
    };

    // basic client validation
    if (!payload.fullName || !payload.email || !payload.phone) {
      if (msg) msg.textContent = "Please complete name, email, and phone.";
      return;
    }

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    try {
      const res = await postJSON(APPS_SCRIPT_URL, payload, { timeoutMs: 12000 });

      // Expect your Apps Script to return { ok: true } on success
      if (res.ok && (res.json?.ok ?? true)) {
        if (msg) msg.textContent = "✅ Thanks! Your pre-approval intake was received. I’ll reach out shortly.";
        formEl.reset();
        window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
      } else {
        const reason = res.json?.error || `(${res.status})`;
        if (msg) msg.textContent = `Could not submit right now ${reason}. Please try again or email me.`;
      }
    } catch (err) {
      if (msg) msg.textContent = "Network error submitting the form. Please try again.";
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
    }
  });
})();