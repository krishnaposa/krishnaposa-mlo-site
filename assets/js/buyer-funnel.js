/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, and Apps Script submit (no-cors to avoid CORS)
*/
(function () {
  // ---- Helpers coming from your mortgage-calc.js ----
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;
  const $ = (sel) => document.querySelector(sel);

  // ---- Apps Script endpoint (your URL) ----
  const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbzt4DK41hW-N8ig4r8NrWyRFNUQi4yQDSAciz3Dchm1Xfm3BeNprN3IPMULWVZemzXl/exec';

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
  $("#intakeForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formEl   = e.currentTarget;
    const submitBn = $("#submitBtn") || formEl.querySelector('button[type="submit"]');
    const msg      = $("#submitMsg");
    const hp       = $("#hp");

    if (hp && hp.value) { msg && (msg.textContent = "Submission blocked (spam check)."); return; }
    msg && (msg.textContent = "");
    submitBn && (submitBn.disabled = true, submitBn.textContent = "Submitting…");

    // Build flat key/value payload (keys become column headers in the Sheet)
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
      // derived/hidden (if present)
      estMonthly: $("#h_estMonthly")?.value || "",
      estDTI:     $("#h_estDTI")?.value || "",
      agentName:  $("#h_agentName")?.value || "",
      agentEmail: $("#h_agentEmail")?.value || "",
      utm:        $("#h_utm")?.value || "",
      debug: "1" // lets you see details in Executions
    };

    // URL-encode once; reuse for beacon or fetch
    const bodyStr = new URLSearchParams(payload).toString();

    let sent = false;
    // 1) Try sendBeacon (CORS-free, very reliable for simple posts)
    if (navigator.sendBeacon) {
      try {
        const blob = new Blob([bodyStr], { type: "application/x-www-form-urlencoded" });
        sent = navigator.sendBeacon(APPS_SCRIPT_URL, blob);
      } catch (_) { sent = false; }
    }

    // 2) Fallback to fetch (opaque success under no-cors is OK)
    if (!sent) {
      try {
        await fetch(APPS_SCRIPT_URL, {
          method: "POST",
          mode: "no-cors",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: bodyStr
        });
        sent = true;
      } catch (_) { sent = false; }
    }

    if (sent) {
      msg && (msg.textContent = "✅ Thanks! Your pre-approval intake was received.");
      formEl.reset();
      window.dataLayer && window.dataLayer.push({ event: "preapproval_submit" });
    } else {
      msg && (msg.textContent = "⚠️ Couldn’t send right now. Please try again.");
    }

    submitBn && (submitBn.disabled = false, submitBn.textContent = "Submit Pre-Approval");
  });
})();