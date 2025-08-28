/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Google Forms submit
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // ===== 1) SET this to your Google Form action (the /formResponse URL) =====
  // Example: "https://docs.google.com/forms/d/e/1FAIpQLSdEXAMPLEID/formResponse"
  const GOOGLE_FORM_ACTION = "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/formResponse";

  // ===== 2) MAP your Google Form "entry.<id>" names here =====
  // Find them in your form's HTML (Preview -> View Source -> look for name="entry.xxxxx")
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
    notes:      "entry.1112680792",
    // Hidden/derived fields — make short-answer questions for them in your Google Form
    estMonthly: "entry.672377788",
    estDTI:     "entry.1531234816",
    agentName:  "entry.816490105",
    agentEmail: "entry.1411194686",
    utm:        "entry.1980121130"
  };

  // DOM helpers
  const $ = (sel) => document.querySelector(sel);
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookMid", "#bookBottom", "#bookSticky"].forEach((q) => { const el = $(q); if (el) el.href = BOOKING_URL; });

  // Realtor co-brand
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName").textContent = data.name || "No agent added";
    $("#agentFirm").textContent = data.firm || "You can add one above";
    $("#agentAvatar").src = data.logo || "";
    $("#h_agentName").value = data.name || "";
    $("#h_agentEmail").value = data.email || "";
  }
  $("#saveAgent")?.addEventListener("click", () => {
    const payload = {
      name: $("#agent_name").value.trim(),
      firm: $("#agent_firm").value.trim(),
      email: $("#agent_email").value.trim(),
      logo: $("#agent_logo").value.trim()
    };
    localStorage.setItem("agent", JSON.stringify(payload));
    drawAgent();
  });
  drawAgent();

  // Quick Qualify calculator
  $("#estimateBtn")?.addEventListener("click", () => {
    const price = num($("#price").value);
    const downInput = ($("#down").value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = ($("#rate").value || cfg.defaultRatePct);
    const ratePct = (rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));
    const zip = ($("#zip").value || "").trim();
    const program = $("#program").value;
    const income = num($("#income").value);
    const debts = num($("#debts").value || 0);

    if (!price || !income) { $("#formMsg").textContent = "Please complete price and income (and down payment if available)."; return; }
    $("#formMsg").textContent = "";

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI").textContent = fmt(res.pAndI);
    $("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi);
    $("#totalPay").textContent = fmt(res.total);
    $("#estimatesWrap").style.display = "grid";

    const dtiEl = $("#dtiLine");
    dtiEl.style.display = "";
    dtiEl.innerHTML = `Estimated DTI: <strong>${(dti * 100).toFixed(1)}%</strong>. Many programs prefer under 43 percent.`;

    if (program === "conventional" && res.ltv > 0.80) {
      $("#pmiLine").style.display = "";
      $("#pmiLine").textContent = "Mortgage insurance estimated due to down payment under 20 percent. This can drop as LTV improves.";
    } else {
      $("#pmiLine").style.display = "none";
    }

    $("#h_estMonthly").value = Math.round(res.total);
    $("#h_estDTI").value = `${(dti * 100).toFixed(1)}%`;
    localStorage.setItem("lastEstimate", JSON.stringify({ price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1) }));

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap").style.display = "none";
    $("#dtiLine").style.display = "none";
    $("#pmiLine").style.display = "none";
    $("#formMsg").textContent = "";
    localStorage.removeItem("lastEstimate");
  });

  // Prefill from saved estimate + UTM chain
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        $("#price").value = saved.price;
        if (saved.down) $("#down").value = saved.down;
        $("#rate").value = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        $("#program").value = saved.program || "conventional";
      }
    } catch(e){}
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");
    $("#h_utm").value = utm;
  })();

  // Google Forms submit (AJAX via no-cors)
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn");
    const msg = $("#submitMsg");
    const hp = $("#hp");

    msg.textContent = "";
    if (hp && hp.value) { msg.textContent = "Submission blocked (spam check)."; return; }

    // Build payload for Google Forms
    const data = new FormData();
    data.append(ENTRY.fullName,   $("#fullName").value.trim());
    data.append(ENTRY.email,      $("#email").value.trim());
    data.append(ENTRY.phone,      $("#phone").value.trim());
    data.append(ENTRY.timeline,   $("#timeline").value);
    data.append(ENTRY.occupancy,  $("#occupancy").value);
    data.append(ENTRY.source,     $("#source").value);
    data.append(ENTRY.estPrice,   $("#estPrice").value.trim());
    data.append(ENTRY.estDown,    $("#estDown").value.trim());
    data.append(ENTRY.employment, $("#employment").value);
    data.append(ENTRY.coBorrower, $("#coBorrower").value);
    data.append(ENTRY.notes,      $("#notes").value.trim());
    // Hidden/derived
    data.append(ENTRY.estMonthly, $("#h_estMonthly").value);
    data.append(ENTRY.estDTI,     $("#h_estDTI").value);
    data.append(ENTRY.agentName,  $("#h_agentName").value);
    data.append(ENTRY.agentEmail, $("#h_agentEmail").value);
    data.append(ENTRY.utm,        $("#h_utm").value);

    // Submit (Google Forms blocks CORS; use no-cors and treat as success)
    submitBtn.disabled = true; submitBtn.textContent = "Submitting…";
    try {
      await fetch(GOOGLE_FORM_ACTION, { method: "POST", mode: "no-cors", body: data });
      msg.textContent = "✅ Thanks! Your pre-approval intake was received. I’ll reach out shortly.";
      formEl.reset();
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
    } catch (err) {
      msg.textContent = "Could not submit right now. Please try again or email me.";
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval";
    }
  });
})();