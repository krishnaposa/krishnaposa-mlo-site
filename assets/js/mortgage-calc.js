/* assets/js/mortgage-calc.js
   Lightweight mortgage helpers exposed as window.MortgageCalc
   Reusable across pages (buyer funnel, calculators, blog embeds).
*/
(function () {
  // ---------- Config ----------
  const cfg = {
    defaultRatePct: 6.75,     // default nominal APR, percent
    defaultPmiPct: 0.6,       // annual PMI as percent of price if LTV>80 (rough)
    insurancePerYear: 1200,   // fallback homeowners insurance
    // ZIP-level fallback map (extend as needed)
    taxRateByZip: {
      "30004": 0.012, "30301": 0.012, "30305": 0.0125, "30309": 0.013
    },
    // NEW: County-level presets for GA (midpoint “effective” rates; directional)
    taxRateByCounty: {
      "Fulton":  0.0105, // ~1.05%
      "Cobb":    0.0100, // ~1.00%
      "Gwinnett":0.0102, // ~1.02%
      "DeKalb":  0.0095, // ~0.95%
      "Forsyth": 0.0118  // ~1.18%
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
  function taxRateFor(price, { zip, county }) {
    if (county && cfg.taxRateByCounty[county]) return cfg.taxRateByCounty[county];
    return cfg.taxRateByZip[zip] ?? 0.012; // conservative fallback ~1.2%
  }

  const calc = {
    monthlyPI(loanAmt, annualRatePct, years = 30) {
      const n = years * 12;
      const m = (annualRatePct / 100) / 12;
      if (!isFinite(loanAmt) || !isFinite(annualRatePct)) return NaN;
      if (m === 0) return loanAmt / n;
      const pow = Math.pow(1 + m, n);
      return loanAmt * (m * pow) / (pow - 1);
    },
    taxesPerMonth(price, zip, county) {
      const rate = taxRateFor(price, { zip, county });
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
    totalMonthly({ price, down, ratePct, program, zip, county }) {
      const loan = Math.max(0, price - (down || 0));
      const pAndI = calc.monthlyPI(loan, ratePct);
      const taxes = calc.taxesPerMonth(price, zip, county);
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