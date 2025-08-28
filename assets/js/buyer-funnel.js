/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and robust Google Forms submit
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // Your live Google Form /formResponse URL
  const GOOGLE_FORM_ACTION = "https://docs.google.com/forms/d/e/1FMqkjaYU8LP2OwSCp_IYyN0U2K3fWr780n8ACjeRfdU/formResponse";
  

  // Your entry IDs (from your form)
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
    estMonthly: "entry.672377788",
    estDTI:     "entry.1531234816",
    agentName:  "entry.816490105",
    agentEmail: "entry.1411194686",
    utm:        "entry.1980121130"
  };

  const $ = (sel) => document.querySelector(sel);

  // Booking links
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => { const el = $(q); if (el) el.href = BOOKING_URL; });

  // Realtor co-brand
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName") && ($("#agentName").textContent = data.name || "No agent added");
    $("#agentFirm") && ($("#agentFirm").textContent = data.firm || "You can add one above");
    $("#agentAvatar") && ($("#agentAvatar").src = data.logo || "");
    $("#h_agentName") && ($("#h_agentName").value = data.name || "");
    $("#h_agentEmail") && ($("#h_agentEmail").value = data.email || "");
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

    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI") && ($("#h_estDTI").value = `${(dti * 100).toFixed(1)}%`);
    localStorage.setItem("lastEstimate", JSON.stringify({ price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1) }));

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine") && ($("#dtiLine").style.display = "none");
    $("#pmiLine") && ($("#pmiLine").style.display = "none");
    $("#formMsg") && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Prefill from saved estimate + UTM chain
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price")) $("#price").value = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate")) $("#rate").value = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch(e){}
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");
    $("#h_utm") && ($("#h_utm").value = utm);
  })();

  // ------- Robust Google Forms submit -------
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp");

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    // Build payload
    const payload = new Map([
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
      [ENTRY.notes,      $("#notes")?.value.trim() || ""],
      [ENTRY.estMonthly, $("#h_estMonthly")?.value || ""],
      [ENTRY.estDTI,     $("#h_estDTI")?.value || ""],
      [ENTRY.agentName,  $("#h_agentName")?.value || ""],
      [ENTRY.agentEmail, $("#h_agentEmail")?.value || ""],
      [ENTRY.utm,        $("#h_utm")?.value || ""]
    ]);

    // Extra fields Google expects
    const fbzx = (crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
    const extra = new Map([["fvv","1"],["pageHistory","0"],["fbzx",fbzx]]);

    // Try fetch (no-cors)
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }
    try {
      const fd = new FormData();
      payload.forEach((v,k)=>fd.append(k,v));
      extra.forEach((v,k)=>fd.append(k,v));
      await fetch(GOOGLE_FORM_ACTION, { method: "POST", mode: "no-cors", body: fd });
    } catch (_) { /* ignore; iframe fallback will run too */ }

    // Iframe fallback: real form POST (most reliable)
    const iframe = document.createElement("iframe");
    iframe.name = "gf_post";
    iframe.style.display = "none";
    document.body.appendChild(iframe);

    const tempForm = document.createElement("form");
    tempForm.action = GOOGLE_FORM_ACTION;
    tempForm.method = "POST";
    tempForm.target = "gf_post";
    tempForm.style.display = "none";

    payload.forEach((v,k)=>{ const i=document.createElement("input"); i.type="hidden"; i.name=k; i.value=v; tempForm.appendChild(i); });
    extra.forEach((v,k)=>{ const i=document.createElement("input"); i.type="hidden"; i.name=k; i.value=v; tempForm.appendChild(i); });

    document.body.appendChild(tempForm);
    tempForm.submit();

    setTimeout(() => {
      tempForm.remove(); iframe.remove();
      if (msg) msg.textContent = "✅ Thanks! Your pre-approval intake was received. I’ll reach out shortly.";
      formEl.reset();
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
    }, 900);
  });
})();