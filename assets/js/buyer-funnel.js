/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Google Forms submit (top-level POST)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // Google Form action (must end with /formResponse)
  const GOOGLE_FORM_ACTION =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/formResponse";

  // Map to your live entry IDs
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

  const $ = (sel) => document.querySelector(sel);

  // Booking links
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q); if (el) el.href = BOOKING_URL;
  });

  // Realtor co-brand
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName")    && ($("#agentName").textContent  = data.name || "No agent added");
    $("#agentFirm")    && ($("#agentFirm").textContent  = data.firm || "You can add one above");
    $("#agentAvatar")  && ($("#agentAvatar").src        = data.logo || "");
    $("#h_agentName")  && ($("#h_agentName").value      = data.name || "");
    $("#h_agentEmail") && ($("#h_agentEmail").value     = data.email || "");
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

  // Quick Qualify calculator
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

    if (!price || !income) { $("#formMsg") && ($("#formMsg").textContent = "Please complete price and income (and down payment if available)."); return; }
    $("#formMsg") && ($("#formMsg").textContent = "");

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI")         && ($("#pAndI").textContent = fmt(res.pAndI));
    $("#taxes")         && ($("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi));
    $("#totalPay")      && ($("#totalPay").textContent = fmt(res.total));
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

    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI")     && ($("#h_estDTI").value     = `${(dti * 100).toFixed(1)}%`);

    localStorage.setItem("lastEstimate",
      JSON.stringify({ price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1) })
    );

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")      && ($("#dtiLine").style.display = "none");
    $("#pmiLine")      && ($("#pmiLine").style.display = "none");
    $("#formMsg")      && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Prefill from saved estimate + UTM
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

  // Build payload from the page
  function buildPayloadMap() {
    return new Map([
      [ENTRY.fullName,   $("#fullName")?.value.trim() || ""],
      [ENTRY.email,      $("#email")?.value.trim() || ""],
      [ENTRY.phone,      $("#phone")?.value.trim() || ""],
      [ENTRY.timeline,   $("#timeline")?.value || ""],
      [ENTRY.occupancy,  $("#occupancy")?.value || ""],
      [ENTRY.source,     $("#source")?.value || ""],
      [ENTRY.estPrice,   $("#estPrice")?.value.trim() || ""],
      [ENTRY.estDown,    $("#estDown")?.value.trim() || ""],
      [ENTRY.employment, $("#employment")?.value || ""],
      [ENTRY.coBorrower, $("#coBorrower")?.value || ""],
      [ENTRY.notes,      $("#notes")?.value.trim() || ""]
    ]);
  }

  // Debug helper: open the exact GET URL you just used manually
  window.openGoogleFormTestURL = function () {
    const p = buildPayloadMap();
    const qs = new URLSearchParams();
    p.forEach((v, k) => qs.set(k, v));
    qs.set("fvv", "1");
    qs.set("pageHistory", "0");
    qs.set("hl", "en");
    qs.set("submit", "Submit");
    window.open(GOOGLE_FORM_ACTION + "?" + qs.toString(), "_blank");
  };

  // Submit to Google Forms with a top-level POST (avoids CORS/CSP/iframe issues)
  $("#intakeForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp");

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    const payload = buildPayloadMap();

    // Extra Google params (add submit + hl like your working test URL)
    const fbzx = (crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
    const extra = new Map([
      ["fvv","1"],
      ["draftResponse","[]"],
      ["pageHistory","0"],
      ["hl","en"],
      ["submit","Submit"],
      ["fbzx",fbzx]
    ]);

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    // Build and POST a temporary form in a new tab
    const tempForm = document.createElement("form");
    tempForm.action = GOOGLE_FORM_ACTION;
    tempForm.method = "POST";
    tempForm.target = "_blank";
    tempForm.style.display = "none";

    payload.forEach((v,k)=>{ const i=document.createElement("input"); i.type="hidden"; i.name=k; i.value=v; tempForm.appendChild(i); });
    extra.forEach((v,k)=>{ const i=document.createElement("input"); i.type="hidden"; i.name=k; i.value=v; tempForm.appendChild(i); });

    document.body.appendChild(tempForm);
    tempForm.submit();
    setTimeout(()=>tempForm.remove(), 600);

    if (msg) msg.textContent = "Submitted. A confirmation tab opened in your browser.";
    formEl.reset();
    window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
  });
})();