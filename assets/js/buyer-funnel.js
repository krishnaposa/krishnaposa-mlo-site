/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Google Forms submit (top-level POST + exact label mapping)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;

  // Use the action exactly as your form shows (includes /u/0/ and ?hl=en)
  const GOOGLE_FORM_ACTION =
    "https://docs.google.com/forms/u/0/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/formResponse?hl=en";

  // Your entry IDs (from your form)
  const ENTRY = {
    fullName:   "entry.1081531616",
    email:      "entry.1665114649",
    phone:      "entry.776689893",
    timeline:   "entry.938852734",   // dropdown
    occupancy:  "entry.223995685",   // dropdown
    source:     "entry.447085241",   // dropdown
    estPrice:   "entry.390780263",
    estDown:    "entry.508547119",
    employment: "entry.1791431821",  // dropdown
    coBorrower: "entry.1836064847",  // dropdown
    notes:      "entry.1112680792"
  };

  // ===== Exact label mapping (RIGHT side must match Google exactly) =====
  const CHOICE_MAP = {
    [ENTRY.timeline]: {
      "asap": "ASAP",
      "30-60 days": "30-60 days",
      "60-90 days": "60-90 days",
      "3-6 months": "3-6 months",
      "6+ months": "6+ months"
    },
    [ENTRY.occupancy]: {
      "primary residence": "Primary Residence", // lower 'r' per source
      "primary": "Primary residence",
      "second home": "Second home",
      "investment": "Investment"
    },
    [ENTRY.source]: {
      "realtor partner": "Realtor Partner",     // lower 'p' per source
      "instagram": "Instagram",
      "facebook": "Facebook",
      "google": "Google",
      "friend or family": "Friend or family",   // lower 'f'
      "other": "Other"
    },
    [ENTRY.employment]: {
      "w2": "W2",
      "self-employed": "Self-employed",         // hyphen & lower 'e'
      "self employed": "Self-employed",
      "1099": "1099",
      "mixed": "Mixed"
    },
    [ENTRY.coBorrower]: {
      "no": "No",
      "yes": "Yes"
    }
  };

  // Choice fields (we’ll also send _sentinel companions for these)
  const CHOICE_FIELDS = [
    ENTRY.timeline,
    ENTRY.occupancy,
    ENTRY.source,
    ENTRY.employment,
    ENTRY.coBorrower
  ];

  // --- Helpers
  const $ = (sel) => document.querySelector(sel);
  const text = (sel) => ($(sel)?.value || "").trim();

  function mapChoice(entryKey, uiLabel) {
    const raw = (uiLabel || "").trim();
    if (!raw) return "";
    const table = CHOICE_MAP[entryKey] || {};
    // Exact match already?
    for (const k in table) {
      if (raw === table[k]) return table[k];
    }
    // Case-insensitive fallback
    const l = raw.toLowerCase();
    if (table[l]) return table[l];
    // Last resort: pass through
    return raw;
  }

  // --- Booking links
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q); if (el) el.href = BOOKING_URL;
  });

  // --- Realtor co-brand
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

  // --- Quick Qualify
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

  // --- Prefill from saved estimate + UTM
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

  // --- Build payload (maps dropdown labels to Google’s exact labels)
  function buildPayloadMap() {
    const getSelectText = (sel) => {
      const el = $(sel);
      if (!el) return "";
      const opt = el.options[el.selectedIndex];
      return (opt?.text || opt?.value || "").trim();
    };

    const uiTimeline   = getSelectText("#timeline");
    const uiOccupancy  = getSelectText("#occupancy");
    const uiSource     = getSelectText("#source");
    const uiEmployment = getSelectText("#employment");
    const uiCoBorrower = getSelectText("#coBorrower");

    return new Map([
      [ENTRY.fullName,   text("#fullName")],
      [ENTRY.email,      text("#email")],
      [ENTRY.phone,      text("#phone")],
      [ENTRY.timeline,   mapChoice(ENTRY.timeline,   uiTimeline)],
      [ENTRY.occupancy,  mapChoice(ENTRY.occupancy,  uiOccupancy)],
      [ENTRY.source,     mapChoice(ENTRY.source,     uiSource)],
      [ENTRY.estPrice,   text("#estPrice")],
      [ENTRY.estDown,    text("#estDown")],
      [ENTRY.employment, mapChoice(ENTRY.employment, uiEmployment)],
      [ENTRY.coBorrower, mapChoice(ENTRY.coBorrower, uiCoBorrower)],
      [ENTRY.notes,      text("#notes")]
    ]);
  }

  // Debug helper: open a GET test URL with current values
  window.openGoogleFormTestURL = function () {
    const p = buildPayloadMap();

    // Sensible defaults if not chosen yet
    const defaults = new Map([
      [ENTRY.timeline,   "ASAP"],
      [ENTRY.occupancy,  "Primary Residence"],
      [ENTRY.source,     "Realtor Partner"],
      [ENTRY.employment, "W2"],
      [ENTRY.coBorrower, "No"]
    ]);
    defaults.forEach((v,k) => { if (!(p.get(k) || "").trim()) p.set(k, v); });

    const qs = new URLSearchParams();
    p.forEach((v, k) => qs.set(k, v));
    qs.set("fvv", "1");
    qs.set("pageHistory", "0");
    qs.set("hl", "en");
    qs.set("submit", "Submit"); // GET only

    window.open(GOOGLE_FORM_ACTION + "&" + qs.toString(), "_blank");
  };

  // --- Submit to Google Forms (top-level POST in a new tab)
  $("#intakeForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const submitBtn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg = $("#submitMsg");
    const hp = $("#hp");

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    const payload = buildPayloadMap();

    // Extras Google expects (no 'submit' here)
    const fbzx = (crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
    const extra = new Map([
      ["fvv","1"],
      ["draftResponse","[]"],
      ["pageHistory","0"],
      ["hl","en"],
      ["fbzx",fbzx]
    ]);

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    const tempForm = document.createElement("form");
    tempForm.action = GOOGLE_FORM_ACTION;
    tempForm.method = "POST";
    tempForm.target = "_blank";
    tempForm.style.display = "none";

    // Entries
    payload.forEach((v,k)=> {
      const i = document.createElement("input");
      i.type = "hidden"; i.name = k; i.value = v;
      tempForm.appendChild(i);
    });

    // Sentinel companions for choice fields
    CHOICE_FIELDS.forEach((k) => {
      const s = document.createElement("input");
      s.type = "hidden";
      s.name = `${k}_sentinel`;
      s.value = "";
      tempForm.appendChild(s);
    });

    // Extras
    extra.forEach((v,k)=> {
      const i = document.createElement("input");
      i.type = "hidden"; i.name = k; i.value = v;
      tempForm.appendChild(i);
    });

    document.body.appendChild(tempForm);
    HTMLFormElement.prototype.submit.call(tempForm);
    setTimeout(()=>tempForm.remove(), 600);

    if (msg) msg.textContent = "Submitted. A confirmation tab opened in your browser.";
    formEl.reset();
    window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
  });
})();