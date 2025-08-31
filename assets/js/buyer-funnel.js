/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Google Forms submit (top-level POST)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // === Google Form action ===
  const GOOGLE_FORM_ACTION =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/formResponse";

  // === Your entry IDs ===
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

  // === Choice mapping (normalize UI text → exact Form labels) ===
  // Keys are lowercased for flexible matching.
  const CHOICE_MAP = {
    [ENTRY.timeline]: {
      "asap": "ASAP",
      "30-60 days": "30-60 days",
      "60-90 days": "60-90 days",
      "3-6 months": "3-6 months",
      "6+ months": "6+ months"
    },
    [ENTRY.occupancy]: {
      "primary residence": "Primary residence", // Google Form expects lower-case "residence"
      "second home": "Second home",
      "investment": "Investment"
    },
    [ENTRY.source]: {
      "realtor partner": "Realtor partner",
      "instagram": "Instagram",
      "facebook": "Facebook",
      "google": "Google",
      "friend or family": "Friend or family",
      "other": "Other"
    },
    [ENTRY.employment]: {
      "w2": "W2",
      "self-employed": "Self-employed",
      "1099": "1099",
      "mixed": "Mixed"
    },
    [ENTRY.coBorrower]: {
      "yes": "Yes",
      "no": "No"
    }
  };

  function normalizeChoice(entryKey, rawValue) {
    if (!rawValue) return "";
    const map = CHOICE_MAP[entryKey] || {};
    return map[String(rawValue).toLowerCase()] || rawValue; // fall back to original
  }

  // --- tiny DOM helper
  const $ = (sel) => document.querySelector(sel);

  // Booking links
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q); if (el) el.href = BOOKING_URL;
  });

  // Realtor co-brand
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    $("#agentName")   && ($("#agentName").textContent  = data.name || "No agent added");
    $("#agentFirm")   && ($("#agentFirm").textContent  = data.firm || "You can add one above");
    $("#agentAvatar") && ($("#agentAvatar").src        = data.logo || "");
    $("#h_agentName") && ($("#h_agentName").value      = data.name || "");
    $("#h_agentEmail")&& ($("#h_agentEmail").value     = data.email || "");
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

    localStorage.setItem("lastEstimate",
      JSON.stringify({ price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1) })
    );

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")       && ($("#dtiLine").style.display = "none");
    $("#pmiLine")       && ($("#pmiLine").style.display = "none");
    $("#formMsg")       && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Prefill from saved estimate + UTM
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

  // ---- Google Forms submit via top-level POST (bypasses CORS/CSP/CORB) ----
  $("#intakeForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp");

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    // Build payload (normalize dropdowns to exact labels)
    const payload = new Map([
      [ENTRY.fullName,   $("#fullName")?.value.trim() || ""],
      [ENTRY.email,      $("#email")?.value.trim() || ""],
      [ENTRY.phone,      $("#phone")?.value.trim() || ""],
      [ENTRY.timeline,   normalizeChoice(ENTRY.timeline,   $("#timeline")?.value || "")],
      [ENTRY.occupancy,  normalizeChoice(ENTRY.occupancy,  $("#occupancy")?.value || "")],
      [ENTRY.source,     normalizeChoice(ENTRY.source,     $("#source")?.value || "")],
      [ENTRY.estPrice,   $("#estPrice")?.value.trim() || ""],
      [ENTRY.estDown,    $("#estDown")?.value.trim() || ""],
      [ENTRY.employment, normalizeChoice(ENTRY.employment, $("#employment")?.value || "")],
      [ENTRY.coBorrower, normalizeChoice(ENTRY.coBorrower, $("#coBorrower")?.value || "")],
      [ENTRY.notes,      $("#notes")?.value.trim() || ""]
    ]);

    // Extra Google params — DO NOT add a field named "submit"
    const fbzx = (crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
    const extra = new Map([["fvv","1"],["pageHistory","0"],["fbzx",fbzx],["hl","en"]]);

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    // Create a one-off form and submit it in a new tab/window
    const tempForm = document.createElement("form");
    tempForm.action = GOOGLE_FORM_ACTION;
    tempForm.method = "POST";
    tempForm.target = "_blank";
    tempForm.style.display = "none";

    const appendHidden = (name, value) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      tempForm.appendChild(input);
    };

    payload.forEach((v, k) => appendHidden(k, v));
    extra.forEach((v, k)   => appendHidden(k, v));
    // NOTE: intentionally *not* appending "submit=Submit" to avoid shadowing form.submit()

    document.body.appendChild(tempForm);
    tempForm.submit();                  // safe: no input named "submit" exists
    setTimeout(() => tempForm.remove(), 600);

    if (msg) msg.textContent = "Submitted. A Google confirmation tab opened in your browser.";
    formEl.reset();
    window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
  });
})();