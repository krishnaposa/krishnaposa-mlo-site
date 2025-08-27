/* assets/js/buyer-funnel.js
   Page wiring for buyer-funnel.html (depends on mortgage-calc.js)
*/
(function () {
  const { cfg, parseNumber: num, fmtCurrency: fmt, fmtPercent: pct, calc } = window.MortgageCalc;

  // ===== CONFIG you can tweak per page (or leave defaults from cfg) =====
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  // Optional: override defaults from cfg here if needed
  // cfg.defaultRatePct = 6.75;
  // cfg.defaultPmiPct = 0.6;
  // cfg.insurancePerYear = 1200;
  // Object.assign(cfg.taxRateByZip, { "30263": 0.0112 });

  // ===== Shortcuts =====
  const $ = (sel) => document.querySelector(sel);

  // ===== Booking links =====
  ["#bookTop", "#bookMid", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q);
    if (el) el.href = BOOKING_URL;
  });

  // ===== Progress bar =====
  const form = $("#qualifyForm");
  const bar = $("#bar");
  function updateProgress() {
    const req = ["#zip", "#price", "#fico", "#income"];
    const filled = req.filter((q) => ($(q)?.value || "").trim()).length;
    const percent = Math.min(100, (filled / req.length) * 60 + 10);
    if (bar) bar.style.width = percent + "%";
  }
  form.addEventListener("input", updateProgress);
  updateProgress();

  // ===== Agent co-brand =====
  function drawAgent() {
    const data = JSON.parse(localStorage.getItem("agent") || "{}");
    const name = data.name || "No agent added";
    const firm = data.firm || "You can add one above";
    $("#agentName").textContent = name;
    $("#agentFirm").textContent = firm;
    $("#agentAvatar").src = data.logo || "";
    // hidden fields on intake
    $("#h_agentName").value = data.name || "";
    $("#h_agentEmail").value = data.email || "";
  }
  $("#saveAgent").addEventListener("click", () => {
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

  // ===== Calculator =====
  $("#estimateBtn").addEventListener("click", () => {
    const price = num($("#price").value);
    const downInput = ($("#down").value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const ratePct = num($("#rate").value || cfg.defaultRatePct) * 1; // already percent
    const zip = ($("#zip").value || "").trim();
    const program = $("#program").value;
    const income = num($("#income").value);
    const debts = num($("#debts").value || 0);

    if (!price || !isFinite(price) || !income) {
      $("#formMsg").textContent = "Please complete price and income (and down payment if available).";
      return;
    }
    $("#formMsg").textContent = "";

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI").textContent = fmt(res.pAndI);
    $("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi);
    $("#totalPay").textContent = fmt(res.total);
    $("#estimatesWrap").style.display = "grid";

    const dtiEl = $("#dtiLine");
    dtiEl.style.display = "";
    dtiEl.innerHTML = "Estimated DTI: <strong>" + (dti * 100).toFixed(1) + "%</strong>. Many programs prefer under 43 percent.";

    // PMI note visibility
    if (program === "conventional" && res.ltv > 0.80) {
      $("#pmiLine").style.display = "";
      $("#pmiLine").textContent = "Mortgage insurance estimated due to down payment under 20 percent. This can drop off as loan to value improves.";
    } else {
      $("#pmiLine").style.display = "none";
    }

    // Hidden fields + save
    $("#h_estMonthly").value = Math.round(res.total);
    $("#h_estDTI").value = (dti * 100).toFixed(1) + "%";
    localStorage.setItem("lastEstimate", JSON.stringify({
      price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1)
    }));

    if (window.dataLayer) window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn").addEventListener("click", () => {
    $("#estimatesWrap").style.display = "none";
    $("#dtiLine").style.display = "none";
    $("#pmiLine").style.display = "none";
    $("#formMsg").textContent = "";
    localStorage.removeItem("lastEstimate");
    updateProgress();
  });

  // Prefill + UTM chain
  (function () {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        $("#price").value = saved.price;
        if (saved.down) $("#down").value = saved.down;
        $("#rate").value = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        $("#program").value = saved.program || "conventional";
      }
    } catch (e) {}
    const utm = location.search.replace("?", "").split("&").filter(Boolean).join("&");
    $("#h_utm").value = utm;
  })();

  // Intake submit tracking
  $("#intakeForm").addEventListener("submit", () => {
    if (window.dataLayer) window.dataLayer.push({ event: "preapproval_submit" });
  });

  // Enter key submits estimate
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      $("#estimateBtn").click();
    }
  });
})();