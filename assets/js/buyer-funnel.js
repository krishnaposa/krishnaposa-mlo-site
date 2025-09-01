/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Apps Script submit (no-cors to avoid CORS)
*/
(function () {
  // ---- Helpers coming from your mortgage-calc.js ----
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;
  const $ = (sel) => document.querySelector(sel);

  // ---- Apps Script endpoint (your URL) ----


  // ---- Booking links ----
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q);
    if (el) el.href = BOOKING_URL;
  });

  // ---- Realtor co-brand ----
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    const name = data.name || "No agent added";
    const firm = data.firm || "You can add one above";
    const logo = data.logo || "";
    $("#agentName")  && ($("#agentName").textContent  = name);
    $("#agentFirm")  && ($("#agentFirm").textContent  = firm);
    $("#agentAvatar")&& ($("#agentAvatar").src        = logo);
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

    // stash derived values so we can send them
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

  // ---- Prefill from saved estimate + UTM chain ----
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

  // ---- Submit to Apps Script (no-cors) ----
 ----
// Drop-in submit handler
const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbxVkjSelQjFJbQc5zNAD9m8soIyPqrZ9ICCq06TmK8lT5evRB0wmLV4mkJ6sSmpbpfG/exec';

document.querySelector("#intakeForm")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const formEl   = e.currentTarget;
  const submitBn = document.querySelector("#submitBtn");
  const msg      = document.querySelector("#submitMsg");
  const hp       = document.querySelector("#hp");

  if (hp && hp.value) { msg && (msg.textContent = "Submission blocked (spam check)."); return; }
  msg && (msg.textContent = "");
  submitBn && (submitBn.disabled = true, submitBn.textContent = "Submitting…");

  const tempForm = document.createElement("form");
  tempForm.action = APPS_SCRIPT_URL;   // your /exec URL
  tempForm.method = "POST";            // simple form post ⇒ no preflight
  tempForm.target = "_self";           // stay on page (or "_blank" if you prefer)
  tempForm.style.display = "none";

  // Helper to add hidden fields
  const add = (name, value) => {
    const i = document.createElement("input");
    i.type = "hidden"; i.name = name; i.value = value ?? "";
    tempForm.appendChild(i);
  };

  // Send clean, flat keys (these become Sheet headers)
  add("fullName",   document.querySelector("#fullName")?.value.trim());
  add("email",      document.querySelector("#email")?.value.trim());
  add("phone",      document.querySelector("#phone")?.value.trim());
  add("timeline",   document.querySelector("#timeline")?.value);
  add("occupancy",  document.querySelector("#occupancy")?.value);
  add("source",     document.querySelector("#source")?.value);
  add("estPrice",   document.querySelector("#estPrice")?.value.trim());
  add("estDown",    document.querySelector("#estDown")?.value.trim());
  add("employment", document.querySelector("#employment")?.value);
  add("coBorrower", document.querySelector("#coBorrower")?.value);
  add("notes",      document.querySelector("#notes")?.value.trim());
  add("estMonthly", document.querySelector("#h_estMonthly")?.value);
  add("estDTI",     document.querySelector("#h_estDTI")?.value);
  add("agentName",  document.querySelector("#h_agentName")?.value);
  add("agentEmail", document.querySelector("#h_agentEmail")?.value);
  add("utm",        document.querySelector("#h_utm")?.value);
  add("debug",      "1");

  document.body.appendChild(tempForm);
  tempForm.submit();                    // works as long as no input named "submit"
  setTimeout(() => tempForm.remove(), 500);

  // Optimistic UI (the Sheet append happens server-side)
  msg && (msg.textContent = "✅ Thanks! Your info was sent.");
  formEl.reset();
  submitBn && (submitBn.disabled = false, submitBn.textContent = "Submit Pre-Approval");
});