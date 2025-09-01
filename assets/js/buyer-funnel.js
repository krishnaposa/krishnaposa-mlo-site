/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and open Google Form (prefilled) for submission
*/
(function () {
  // ---- Helpers coming from your mortgage-calc.js ----
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;
  const $ = (sel) => document.querySelector(sel);

  // ---- Google Form (VIEW) URL + entry IDs ----
  // Users will finish and submit on Google’s page.
  const GOOGLE_FORM_VIEW =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/viewform";

  // Your live entry IDs
  const ENTRY = {
    fullName:   "entry.1081531616",
    email:      "entry.1665114649",
    phone:      "entry.776689893",
    timeline:   "entry.938852734",   // (e.g., ASAP)
    occupancy:  "entry.223995685",   // (Primary residence / Second home / Investment)
    source:     "entry.447085241",   // (Realtor partner / Instagram / …)
    estPrice:   "entry.390780263",
    estDown:    "entry.508547119",
    employment: "entry.1791431821",  // (W2 / Self-employed / 1099 / Mixed)
    coBorrower: "entry.1836064847",  // (Yes / No)
    notes:      "entry.1112680792"
  };

  // ---- Booking links ----
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q);
    if (el) el.href = BOOKING_URL;
  });

  // ---- Realtor co-brand ----
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName")   && ($("#agentName").textContent  = data.name || "No agent added");
    $("#agentFirm")   && ($("#agentFirm").textContent  = data.firm || "You can add one above");
    $("#agentAvatar") && ($("#agentAvatar").src        = data.logo || "");
  }
  $("#saveAgent")?.addEventListener("click", () => {
    const payload = {
      name:  $("#agent_name")?.value.trim()  || "",
      firm:  $("#agent_firm")?.value.trim()  || "",
      email: $("#agent_email")?.value.trim() || "",
      logo:  $("#agent_logo")?.value.trim()  || ""
    };
    localStorage.setItem("agent", JSON.stringify(payload));
    drawAgent();
  });
  drawAgent();

  // ---- Quick Qualify calculator ----
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

    if (!price || !income) {
      $("#formMsg") && ($("#formMsg").textContent = "Please complete price and income (and down payment if available).");
      return;
    }
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

    // Stash derived values in case you ever want them again
    localStorage.setItem("lastEstimate", JSON.stringify({
      price, down, rate: ratePct, program,
      monthly: Math.round(res.total),
      dti: (dti * 100).toFixed(1)
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

  // ---- Prefill from saved estimate (for convenience) ----
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price"))   $("#price").value   = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate"))    $("#rate").value    = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch(e){}
  })();

  // ---- Intake: open the Google Form (prefilled) and let user submit there ----
  $("#intakeForm")?.addEventListener("submit", (e) => {
    e.preventDefault();

    // Collect current values from your page
    const values = {
      [ENTRY.fullName]:   $("#fullName")?.value.trim()          || "",
      [ENTRY.email]:      $("#email")?.value.trim()             || "",
      [ENTRY.phone]:      $("#phone")?.value.trim()             || "",
      [ENTRY.timeline]:   $("#timeline")?.value                 || "",
      [ENTRY.occupancy]:  $("#occupancy")?.value                || "",
      [ENTRY.source]:     $("#source")?.value                   || "",
      [ENTRY.estPrice]:   $("#estPrice")?.value.trim()          || "",
      [ENTRY.estDown]:    $("#estDown")?.value.trim()           || "",
      [ENTRY.employment]: $("#employment")?.value               || "",
      [ENTRY.coBorrower]: $("#coBorrower")?.value               || "",
      [ENTRY.notes]:      $("#notes")?.value.trim()             || ""
    };

    // Build a prefill URL (exact option text is already used in your selects)
    const u = new URL(GOOGLE_FORM_VIEW);
    const sp = new URLSearchParams();
    Object.entries(values).forEach(([k, v]) => { if (v) sp.set(k, v); });
    // Optional (helps Forms):
    sp.set("fvv", "1"); sp.set("pageHistory", "0");

    u.search = sp.toString();

    // Mobile-friendly: navigate in the same tab (won’t be blocked)
    window.location.href = u.toString();
  });
})();