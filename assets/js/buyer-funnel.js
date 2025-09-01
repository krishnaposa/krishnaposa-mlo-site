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
  /* ===== Realtor co-brand (robust) ===== */
function drawAgent() {
  const data = JSON.parse(localStorage.getItem("agent") || "{}");
  const name = data.name || "No agent added";
  const firm = data.firm || "You can add one above";
  const logo = data.logo || "";

  const nameEl  = document.querySelector("#agentName");
  const firmEl  = document.querySelector("#agentFirm");
  const avatar  = document.querySelector("#agentAvatar");
  const hName   = document.querySelector("#h_agentName");
  const hEmail  = document.querySelector("#h_agentEmail");

  if (nameEl) nameEl.textContent = name;
  if (firmEl) firmEl.textContent = firm;

  if (avatar) {
    // hide by default if no logo
    if (!logo) {
      avatar.removeAttribute("src");
      avatar.style.display = "none";
    } else {
      avatar.style.display = "block";
      avatar.src = logo;
      // if the provided URL is bad, hide the image to avoid the broken icon
      avatar.onerror = () => { avatar.style.display = "none"; };
    }
  }

  if (hName)  hName.value  = data.name  || "";
  if (hEmail) hEmail.value = data.email || "";
}

// Bind after DOM is parsed (your script is `defer`, but this keeps it bulletproof)
document.addEventListener("DOMContentLoaded", () => {
  // Event delegation so it still works if the button is re-rendered
  document.addEventListener("click", (evt) => {
    const btn = evt.target.closest("#saveAgent");
    if (!btn) return;

    // Prevent any accidental form submits
    evt.preventDefault();

    const name  = (document.querySelector("#agent_name")?.value || "").trim();
    const firm  = (document.querySelector("#agent_firm")?.value || "").trim();
    const email = (document.querySelector("#agent_email")?.value || "").trim();
    const logo  = (document.querySelector("#agent_logo")?.value || "").trim();

    // Save
    localStorage.setItem("agent", JSON.stringify({ name, firm, email, logo }));

    // Reflect in UI + hidden fields
    drawAgent();

    // Tiny confirmation
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Saved ✓";
    setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 900);
  });

  // First paint
  drawAgent();
});

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