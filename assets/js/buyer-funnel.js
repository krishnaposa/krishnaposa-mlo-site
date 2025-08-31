/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and submit via Apps Script (with Google Forms fallback)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // ===== 0) ENDPOINTS =====
  // Your Apps Script Web App (Deploy > New deployment > Web app > "Anyone")
  const APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxVkjSelQjFJbQc5zNAD9m8soIyPqrZ9ICCq06TmK8lT5evRB0wmLV4mkJ6sSmpbpfG/exec";

  // Your Google Form's /formResponse URL (fallback)
  const GOOGLE_FORM_ACTION =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/formResponse";

  // Map your Google Form entry IDs (keep only questions that still exist)
  const ENTRY = {
    fullName:   "entry.1081531616",
    email:      "entry.1665114649",
    phone:      "entry.776689893",
    timeline:   "entry.938852734",
    occupancy:  "entry.223995685",
    source:     "entry.447085241",
    estPrice:   "entry.390780263",
    estDown:    "entry.508547119",
    employment: "entry.1791431821",
    coBorrower: "entry.1836064847",
    notes:      "entry.1112680792"
  };

  // ===== 1) SMALL HELPERS =====
  const $ = (sel) => document.querySelector(sel);
  const getVal = (q) => ($(q)?.value || "").trim();

  // Booking links
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => { const el = $(q); if (el) el.href = BOOKING_URL; });

  // ===== 2) REALTOR CO-BRAND (localStorage) =====
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName")   && ($("#agentName").textContent   = data.name || "No agent added");
    $("#agentFirm")   && ($("#agentFirm").textContent   = data.firm || "You can add one above");
    $("#agentAvatar") && ($("#agentAvatar").src         = data.logo || "");
    $("#h_agentName") && ($("#h_agentName").value       = data.name || "");
    $("#h_agentEmail")&& ($("#h_agentEmail").value      = data.email || "");
  }
  $("#saveAgent")?.addEventListener("click", () => {
    const payload = {
      name: getVal("#agent_name"),
      firm: getVal("#agent_firm"),
      email: getVal("#agent_email"),
      logo: getVal("#agent_logo")
    };
    localStorage.setItem("agent", JSON.stringify(payload));
    drawAgent();
  });
  drawAgent();

  // ===== 3) QUICK QUALIFY (estimate) =====
  $("#estimateBtn")?.addEventListener("click", () => {
    const price = num(getVal("#price"));
    const downInput = getVal("#down");
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = (getVal("#rate") || cfg.defaultRatePct);
    const ratePct = (rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));
    const zip = getVal("#zip");
    const program = $("#program")?.value || "conventional";
    const income = num(getVal("#income"));
    const debts = num(getVal("#debts") || 0);

    if (!price || !income) { $("#formMsg") && ($("#formMsg").textContent = "Please complete price and income (and down payment if available)."); return; }
    $("#formMsg") && ($("#formMsg").textContent = "");

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI")        && ($("#pAndI").textContent = fmt(res.pAndI));
    $("#taxes")        && ($("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi));
    $("#totalPay")     && ($("#totalPay").textContent = fmt(res.total));
    $("#estimatesWrap")&& ($("#estimatesWrap").style.display = "grid");

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

    // write derived fields for submit
    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI")     && ($("#h_estDTI").value     = `${(dti * 100).toFixed(1)}%`);

    // cache a bit
    localStorage.setItem("lastEstimate", JSON.stringify({
      price, down, rate: ratePct, program,
      monthly: Math.round(res.total), dti: (dti * 100).toFixed(1)
    }));

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")      && ($("#dtiLine").style.display = "none");
    $("#pmiLine")      && ($("#pmiLine").style.display = "none");
    $("#formMsg")      && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Prefill from saved estimate + UTM chain
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price"))   $("#price").value = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate"))    $("#rate").value = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch(e){}
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");
    $("#h_utm") && ($("#h_utm").value = utm);
  })();

  // ===== 4) SUBMIT HANDLER (Apps Script first, Forms fallback) =====
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp");

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    // Normalize a couple of selects to match your Form choice text exactly
    const normalize = (s) => (s || "").trim();

    // Build a clean JSON payload for Apps Script
    const cleanPayload = {
      fullName:   getVal("#fullName"),
      email:      getVal("#email"),
      phone:      getVal("#phone"),
      timeline:   normalize($("#timeline")?.value),
      occupancy:  normalize($("#occupancy")?.value),             // "Primary residence" | "Second home" | "Investment"
      source:     normalize($("#source")?.value),                 // "Realtor partner" | "Instagram" | ...
      estPrice:   getVal("#estPrice"),
      estDown:    getVal("#estDown"),
      employment: normalize($("#employment")?.value),            // "W2" | "Self-employed" | "1099" | "Mixed"
      coBorrower: normalize($("#coBorrower")?.value),            // "Yes" | "No"
      notes:      getVal("#notes"),
      // hidden/derived (if present in DOM)
      estMonthly: getVal("#h_estMonthly"),
      estDTI:     getVal("#h_estDTI"),
      agentName:  getVal("#h_agentName"),
      agentEmail: getVal("#h_agentEmail"),
      utm:        getVal("#h_utm"),
      meta: {
        userAgent: navigator.userAgent,
        page: location.href,
        ts: Date.now()
      }
    };

    // Build Google Forms payload (only fields that exist in the form)
    const gf = new FormData();
    gf.append(ENTRY.fullName,   cleanPayload.fullName);
    gf.append(ENTRY.email,      cleanPayload.email);
    gf.append(ENTRY.phone,      cleanPayload.phone);
    gf.append(ENTRY.timeline,   cleanPayload.timeline);
    gf.append(ENTRY.occupancy,  cleanPayload.occupancy);
    gf.append(ENTRY.source,     cleanPayload.source);
    gf.append(ENTRY.estPrice,   cleanPayload.estPrice);
    gf.append(ENTRY.estDown,    cleanPayload.estDown);
    gf.append(ENTRY.employment, cleanPayload.employment);
    gf.append(ENTRY.coBorrower, cleanPayload.coBorrower);
    gf.append(ENTRY.notes,      cleanPayload.notes);
    // Google likes a couple of extras; harmless if ignored
    gf.append("fvv", "1");
    gf.append("pageHistory", "0");

    // UI state
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    // 4a) Try Apps Script JSON (cleanest)
    let scriptWorked = false;
    try {
      const res = await fetch(APPS_SCRIPT_URL, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cleanPayload)
      });
      if (res.ok) scriptWorked = true;
    } catch { /* network / CORS */ }

    if (scriptWorked) {
      if (msg) msg.textContent = "✅ Thanks! Your pre-approval intake was received.";
      formEl.reset();
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit", via: "apps_script" });
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
      return;
    }

    // 4b) Fallback — POST to Google Forms in a new tab (bypasses CORS/CSP)
    try {
      const tempForm = document.createElement("form");
      tempForm.action = GOOGLE_FORM_ACTION;
      tempForm.method = "POST";
      tempForm.target = "_blank";
      tempForm.style.display = "none";
      // copy fields
      for (const [k, v] of gf.entries()) {
        const i = document.createElement("input");
        i.type = "hidden"; i.name = k; i.value = v;
        tempForm.appendChild(i);
      }
      document.body.appendChild(tempForm);
      // submit the DOM form element
      tempForm.submit();
      setTimeout(() => tempForm.remove(), 600);

      if (msg) msg.textContent = "Submitted. A Google confirmation tab opened.";
      formEl.reset();
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit", via: "google_form_fallback" });
    } catch {
      if (msg) msg.textContent = "Could not submit right now. Please try again or email me.";
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
    }
  });
})();