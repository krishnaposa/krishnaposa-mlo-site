/* assets/js/calculators.js — uses MortgageCalc for math; handles UI + PDF */
(function () {
  const { parseNumber: num, fmtCurrency: fmt, fmtPercent: pct, calc, cfg } = window.MortgageCalc;

  // ---------- Affordability ----------
  // Target DTI for affordability. You can tweak this to 0.41–0.45 range if desired.
  const AFF_DTI_TARGET = 0.43;

  function priceFromConstraints({ income, debts, ratePct, down, zip, county }) {
    let lo = 50_000, hi = 2_000_000, guess = 0, best = 0;
    for (let i = 0; i < 32; i++) {
      guess = (lo + hi) / 2;
      const res = calc.totalMonthly({ price: guess, down, ratePct, program: "conventional", zip, county });
      const dti = calc.dti(res.total, debts, income);
      if (!isFinite(dti)) break;
      if (dti <= AFF_DTI_TARGET) { best = guess; lo = guess; } else { hi = guess; }
    }
    return best;
  }

  function affCalc() {
    const income = num(document.getElementById("aff_income").value);
    const debts = num(document.getElementById("aff_debts").value || 0);
    const rateInput = document.getElementById("aff_rate").value || cfg.defaultRatePct;
    const ratePct = (rateInput.toString().trim().endsWith("%") ? num(rateInput) * 100 : num(rateInput));
    const zip = (document.getElementById("aff_zip").value || "").trim();
    const county = (document.getElementById("aff_county").value || "").trim() || null;
    const downInput = (document.getElementById("aff_down").value || "").trim();
    const downVal = downInput.endsWith("%") ? num(downInput) /* decimal */ : num(downInput || 0);

    if (!income) { alert("Please enter gross monthly income."); return; }

    // If down given as percent, iterate with that percent; else use absolute
    function computePrice() {
      let priceGuess = priceFromConstraints({ income, debts, ratePct, down: 0, zip, county });
      if (downInput.endsWith("%")) {
        const downAmt = priceGuess * downVal; // downVal is decimal if endsWith("%")
        priceGuess = priceFromConstraints({ income, debts, ratePct, down: downAmt, zip, county });
      } else {
        priceGuess = priceFromConstraints({ income, debts, ratePct, down: downVal, zip, county });
      }
      return priceGuess;
    }

    const price = computePrice();
    document.getElementById("aff_price").textContent = price ? fmt(price) : "$—";
    document.getElementById("aff_note").textContent =
      `Targets total DTI near ${pct(AFF_DTI_TARGET)}. Final numbers vary by taxes, insurance, program, and credit.`;
    if (window.dataLayer) dataLayer.push({ event: "calc_affordability" });
  }

  document.getElementById("aff_calc").addEventListener("click", affCalc);
  document.getElementById("aff_reset").addEventListener("click", () => {
    document.getElementById("aff_price").textContent = "$—";
    document.getElementById("aff_note").textContent = "";
  });

  // ---------- Shared amortization helper (used by Refi + Payment overrides) ----------
  function monthlyPI(loan, ratePct, years = 30) {
    const n = years * 12;
    const m = (ratePct / 100) / 12;
    if (m === 0) return loan / n;
    const pow = Math.pow(1 + m, n);
    return loan * (m * pow) / (pow - 1);
  }

  // ---------- Monthly Payment ----------
  function payCalc() {
    const price = num(document.getElementById("pay_price").value);
    const downInput = (document.getElementById("pay_down").value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = (document.getElementById("pay_rate").value || cfg.defaultRatePct);
    const ratePct = (rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));
    const zip = (document.getElementById("pay_zip").value || "").trim();
    const county = (document.getElementById("pay_county").value || "").trim() || null;
    const program = document.getElementById("pay_program").value;

    // New: read term + ARM type (if present)
    const termEl = document.getElementById("pay_term");
    const termYears = Math.max(1, parseInt(termEl ? termEl.value : "30", 10));
    const armType = (document.getElementById("arm_type") && document.getElementById("arm_type").value) || null;

    if (!price) { alert("Please enter home price."); return; }

    // For taxes/insurance/MI logic, treat ARM like conventional.
    const programForTI = (program === "arm") ? "conventional" : program;

    // Base components using your MortgageCalc engine (for taxes, ins, pmi, ltv, etc.)
    const res = calc.totalMonthly({ price, down, ratePct, program: programForTI, zip, county });

    // Override P+I to respect selected term (15 or 30) and ARM choice.
    const loanAmount = Math.max(0, price - down);
    let pAndI = monthlyPI(loanAmount, ratePct, termYears);

    // Recompose totals with the overridden P+I
    const taxesInsPmi = res.taxes + res.ins + res.pmi;
    const total = pAndI + taxesInsPmi;

    document.getElementById("pay_pi").textContent = fmt(pAndI);
    document.getElementById("pay_ti").textContent = fmt(taxesInsPmi);
    document.getElementById("pay_total").textContent = fmt(total);

    // PMI note: show for Conventional and ARM when LTV > 80%
    const pmiNote = document.getElementById("pay_pmi_note");
    if ((programForTI === "conventional") && res.ltv > 0.80) {
      pmiNote.style.display = "";
      pmiNote.textContent = "PMI estimated due to LTV above 80 percent. It can fall off when equity improves.";
    } else {
      pmiNote.style.display = "none";
      pmiNote.textContent = "";
    }

    if (window.dataLayer) {
      dataLayer.push({
        event: "calc_payment",
        loan_program: program,
        loan_program_for_ti: programForTI,
        term_years: termYears,
        arm_type: armType
      });
    }
  }

  document.getElementById("pay_calc").addEventListener("click", payCalc);
  document.getElementById("pay_reset").addEventListener("click", () => {
    ["pay_pi", "pay_ti", "pay_total"].forEach(id => document.getElementById(id).textContent = "$—");
    const n = document.getElementById("pay_pmi_note");
    n.style.display = "none"; n.textContent = "";
  });

  // ---------- Refi Break-Even ----------
  function refiCalc() {
    const loan = num(document.getElementById("refi_loan").value);
    const oldRateField = (document.getElementById("refi_old_rate").value || cfg.defaultRatePct);
    const newRateField = (document.getElementById("refi_new_rate").value || cfg.defaultRatePct);
    const costs = num(document.getElementById("refi_costs").value || 0);

    if (!loan) { alert("Please enter current loan balance."); return; }

    const oldRatePct = (oldRateField.toString().trim().endsWith("%") ? num(oldRateField) * 100 : num(oldRateField));
    const newRatePct = (newRateField.toString().trim().endsWith("%") ? num(newRateField) * 100 : num(newRateField));

    const oldPI = monthlyPI(loan, oldRatePct);
    const newPI = monthlyPI(loan, newRatePct);
    const savings = Math.max(0, oldPI - newPI);
    const months = savings > 0 ? Math.ceil(costs / savings) : Infinity;

    document.getElementById("refi_savings").textContent = fmt(savings);
    document.getElementById("refi_months").textContent = isFinite(months) ? months : "N/A";

    if (window.dataLayer) dataLayer.push({ event: "calc_refi" });
  }

  document.getElementById("refi_calc").addEventListener("click", refiCalc);
  document.getElementById("refi_reset").addEventListener("click", () => {
    document.getElementById("refi_savings").textContent = "$—";
    document.getElementById("refi_months").textContent = "—";
  });

  // ---------- Extra Payment Impact ----------
  function extraCalc() {
    const loan = num(document.getElementById("extra_loan").value);
    const rateField = (document.getElementById("extra_rate").value || cfg.defaultRatePct);
    const years = Math.max(1, parseInt(document.getElementById("extra_years").value || "30", 10));
    const extra = num(document.getElementById("extra_add").value || 0);

    if (!loan) { alert("Please enter loan amount."); return; }
    const ratePct = (rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));

    const base = monthlyPI(loan, ratePct, years);
    let balance = loan;
    let month = 0;
    const m = (ratePct / 100) / 12;
    const basePay = base;
    const payWithExtra = base + (extra || 0);

    // Amortize with extra payment
    while (balance > 0 && month < years * 12 + 240 /* safety cap */) {
      const interest = balance * m;
      let principal = payWithExtra - interest;
      if (principal <= 0) break; // payment too small
      if (principal > balance) principal = balance;
      balance -= principal;
      month++;
    }

    const baseMonths = years * 12;
    const savedMonths = Math.max(0, baseMonths - month);

    document.getElementById("extra_base").textContent = fmt(basePay);
    document.getElementById("extra_with").textContent = fmt(payWithExtra);
    document.getElementById("extra_time").textContent = savedMonths ? `${savedMonths} months` : "—";
    document.getElementById("extra_note").textContent = savedMonths
      ? `At this rate you could finish about ${Math.floor(savedMonths/12)} years and ${savedMonths%12} months sooner (estimate).`
      : `If time saved shows “—”, try increasing the extra payment.`;

    if (window.dataLayer) dataLayer.push({ event: "calc_extra_payment" });
  }

  document.getElementById("extra_calc").addEventListener("click", extraCalc);
  document.getElementById("extra_reset").addEventListener("click", () => {
    document.getElementById("extra_base").textContent = "$—";
    document.getElementById("extra_with").textContent = "$—";
    document.getElementById("extra_time").textContent = "—";
    document.getElementById("extra_note").textContent = "";
  });

  // ---------- Print-to-PDF (single panel) ----------
  function printPanel(selector, title = "Mortgage Calculator") {
    const node = document.querySelector(selector);
    if (!node) return alert("Section not found.");
    const win = window.open("", "_blank", "noopener,noreferrer,width=900,height=1200");
    const when = new Date().toLocaleString();
    win.document.write(`
      <!doctype html><html><head>
        <meta charset="utf-8">
        <title>${title}</title>
        <link rel="stylesheet" href="https://www.krishposa.com/assets/css/styles.css">
        <style>
          @page { size: A4; margin: 16mm; }
          body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }
          .print-wrap { max-width: 800px; margin: 0 auto; }
          .print-header { margin-bottom: 12px; }
          .print-header h1 { font-size: 20px; margin: 0 0 4px; }
          .tiny { font-size: 12px; color: #666; }
          .card { box-shadow: none !important; border: 1px solid #ddd; }
        </style>
      </head><body>
        <div class="print-wrap">
          <div class="print-header">
            <h1>${title}</h1>
            <div class="tiny">Generated ${when} • krishposa.com</div>
          </div>
          ${node.outerHTML}
        </div>
        <script>window.onload = () => { window.print(); setTimeout(()=>window.close(), 300); }<\/script>
      </body></html>
    `);
    win.document.close();
  }

  // Bind buttons
  document.querySelectorAll('[data-print]').forEach(btn => {
    btn.addEventListener('click', () => {
      const sel = btn.getAttribute('data-print');
      const title =
        sel === '#affCard'  ? 'Affordability Results' :
        sel === '#payCard'  ? 'Monthly Payment Results' :
        sel === '#refiCard' ? 'Refi Break-Even Results' :
        sel === '#extraCard'? 'Extra Payment Impact Results' :
                              'Calculator Results';
      printPanel(sel, title);
    });
  });
})();