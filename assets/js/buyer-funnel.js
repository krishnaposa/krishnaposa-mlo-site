/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Apps Script submit (no-cors to avoid CORS)
*/
(function () {
  // ---- Helpers coming from your mortgage-calc.js ----
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;
  const $ = (sel) => document.querySelector(sel);

  // ---- Apps Script endpoint (your URL) ----
  const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbxyfF8OSwW88iUaCZ3sGDAD50aQLe55n2d297fqqakag4wq-R6uM1AjTQzNiVmWL5Tf/exec';

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
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formEl   = e.currentTarget;
    const submitBtn= $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg      = $("#submitMsg");
    const hp       = $("#hp"); // honeypot

    if (msg) msg.textContent = "";
    if (hp && hp.value) { if (msg) msg.textContent = "Submission blocked (spam check)."; return; }

    // Read visible fields
    const fullName   = $("#fullName")?.value.trim()   || "";
    const email      = $("#email")?.value.trim()      || "";
    const phone      = $("#phone")?.value.trim()      || "";
    const timeline   = $("#timeline")?.value          || "";
    const occupancy  = $("#occupancy")?.value         || "";
    const source     = $("#source")?.value            || "";
    const estPrice   = $("#estPrice")?.value.trim()   || "";
    const estDown    = $("#estDown")?.value.trim()    || "";
    const employment = $("#employment")?.value        || "";
    const coBorrower = $("#coBorrower")?.value        || "";
    const notes      = $("#notes")?.value.trim()      || "";

    // Pull derived + agent data
    let monthly = "", dti = "", program = "";
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved) {
        monthly = saved.monthly ?? "";
        dti     = saved.dti ?? "";
        program = saved.program ?? "";
      }
    } catch(_) {}

    const agent = JSON.parse(localStorage.getItem("agent") || "{}");
    const agentName  = agent.name  || "";
    const agentEmail = agent.email || "";

    // UTM chain from URL
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");

    // Build a clean payload (column names become headers in the Sheet)
    const payload = {
      fullName, email, phone,
      timeline, occupancy, source,
      estPrice, estDown, employment, coBorrower, notes,
      estMonthly: monthly, estDTI: dti, program,
      agentName, agentEmail,
      utm,
      userAgent: navigator.userAgent,
      page: location.href,
      submittedAt: new Date().toISOString()
    };

    // Convert to x-www-form-urlencoded to avoid preflight, and send with no-cors
    const body = new URLSearchParams();
    Object.entries(payload).forEach(([k,v]) => body.append(k, String(v)));

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Submitting…"; }

    try {
      await fetch(APPS_SCRIPT_URL, {
        method: "POST",
        mode: "no-cors", // <— key to bypass CORS block
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body
      });

      // We can’t read the response in no-cors, so we optimistically confirm.
      if (msg) msg.textContent = "✅ Thanks! Your pre-approval intake was received. I’ll reach out shortly.";
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
      formEl.reset();
    } catch (err) {
      if (msg) msg.textContent = "❌ Sorry—couldn’t submit right now. Please try again, or email krishna.posa@gmail.com.";
      console.error("Apps Script submit failed:", err);
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Submit Pre-Approval"; }
    }
  });
})();