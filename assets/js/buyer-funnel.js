/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand, open Google Form for intake (no in-page submit)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc;
  const $ = (sel) => document.querySelector(sel);

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
    $("#agentAvatar") && ($("#agentAvatar").src        = data.logo || "https://www.krishposa.com/assets/img/realtor.png");
    $("#agentAvatar") && ($("#agentAvatar").style.display = "block";
    // If you keep hidden fields elsewhere, you can still populate them here:
    $("#h_agentName")  && ($("#h_agentName").value  = data.name || "");
    $("#h_agentEmail") && ($("#h_agentEmail").value = data.email || "");
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

    // Save for convenience / refilling later
    localStorage.setItem("lastEstimate", JSON.stringify({
      price,
      down,
      rate: ratePct,
      program,
      monthly: Math.round(res.total),
      dti: (dti * 100).toFixed(1)
    }));

    // If you still keep hidden derived fields around:
    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI")     && ($("#h_estDTI").value     = `${(dti * 100).toFixed(1)}%`);

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")      && ($("#dtiLine").style.display = "none");
    $("#pmiLine")      && ($("#pmiLine").style.display = "none");
    $("#formMsg")      && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // ---- Prefill from saved estimate ----
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

  // ---- Open Google Form button: keep href static, append UTM if present (optional) ----
  (function () {
    const btn = $("#openGoogleForm");
    if (!btn) return;

    // If you want to pass current page UTM parameters along to the Form as a single "utm" param:
    const qs = location.search.replace(/^\?/, "");
    if (qs) {
      try {
        const url = new URL(btn.href || "", location.href);
        // append utm as a single blob (you can map it to a Form field later if desired)
        const existing = url.searchParams.get("utm");
        url.searchParams.set("utm", existing ? `${existing}&${qs}` : qs);
        btn.href = url.toString();
      } catch (_) {
        /* leave original href */
      }
    }

    // Optional: analytics
    btn.addEventListener("click", () => {
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: "open_google_form" });
    });
  })();

  // ---- IMPORTANT: removed any submit handler for #intakeForm ----
  // We no longer intercept nor post data from this page. Users complete
  // and submit directly on the Google Form in a new tab.
})();