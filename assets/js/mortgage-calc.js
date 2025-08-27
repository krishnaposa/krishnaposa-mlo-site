/* assets/js/mortgage-calc.js
   Lightweight mortgage helpers exposed as window.MortgageCalc
   Usage: const { cfg, parseNumber, fmtCurrency, fmtPercent, calc } = MortgageCalc;
*/
(function () {
  const cfg = {
    defaultRatePct: 6.75,     // default nominal APR, percent
    defaultPmiPct: 0.6,       // annual PMI as percent of price if LTV>80 (rough)
    insurancePerYear: 1200,   // fallback homeowners insurance
    taxRateByZip: {           // rough millage map; extend for accuracy
      "30004": 0.012, "30301": 0.012, "30305": 0.0125, "30309": 0.013
    }
  };

  // ---------- Formatting & parsing ----------
  function parseNumber(v) {
    if (v == null) return NaN;
    v = String(v).trim();
    if (!v) return NaN;
    if (v.endsWith("%")) return parseFloat(v) / 100;
    return parseFloat(v.replace(/[, \t$\u00A0]/g, ""));
  }
  function fmtCurrency(v) {
    return isFinite(v)
      ? v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
      : "$—";
  }
  function fmtPercent(v) {
    return (v * 100).toFixed(1) + "%";
  }

  // ---------- Core calcs ----------
  const calc = {
    monthlyPI(loanAmt, annualRatePct, years = 30) {
      const n = years * 12;
      const m = (annualRatePct / 100) / 12;
      if (!isFinite(loanAmt) || !isFinite(annualRatePct)) return NaN;
      if (m === 0) return loanAmt / n;
      const pow = Math.pow(1 + m, n);
      return loanAmt * (m * pow) / (pow - 1);
    },
    taxesPerMonth(price, zip) {
      const rate = cfg.taxRateByZip[zip] ?? 0.012;
      return (price * rate) / 12;
    },
    insurancePerMonth() {
      return cfg.insurancePerYear / 12;
    },
    pmiPerMonth(price, ltv, program, annualPmiPctOverride) {
      if (program !== "conventional" || ltv <= 0.80) return 0;
      const pct = (annualPmiPctOverride ?? cfg.defaultPmiPct) / 100;
      return (price * pct) / 12;
    },
    totalMonthly({ price, down, ratePct, program, zip }) {
      const loan = Math.max(0, price - (down || 0));
      const pAndI = calc.monthlyPI(loan, ratePct);
      const taxes = calc.taxesPerMonth(price, zip);
      const ins = calc.insurancePerMonth();
      const ltv = price ? loan / price : 0;
      const pmi = calc.pmiPerMonth(price, ltv, program);
      return { loan, ltv, pAndI, taxes, ins, pmi, total: pAndI + taxes + ins + pmi };
    },
    dti(totalMonthlyHousing, otherMonthlyDebts, grossMonthlyIncome) {
      if (!grossMonthlyIncome) return NaN;
      return (totalMonthlyHousing + (otherMonthlyDebts || 0)) / grossMonthlyIncome;
    }
  };

  // ---------- Public API ----------
  window.MortgageCalc = {
    cfg,
    parseNumber,
    fmtCurrency,
    fmtPercent,
    calc
  };
})();