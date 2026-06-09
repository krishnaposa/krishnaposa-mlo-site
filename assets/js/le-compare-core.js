/* Shared Loan Estimate comparison math — used by le-compare.js and le-upload.js */
(function (global) {
  const num = (v) => {
    if (v === null || v === undefined || v === '') return 0;
    const s = String(v).replace(/[%,$\s]/g, '');
    return s ? parseFloat(s) : 0;
  };

  const pct = (v) => num(v) / 100;

  function pmt(rate, nper, pv) {
    if (rate === 0) return -(pv / nper);
    const rf = Math.pow(1 + rate, nper);
    return -(pv * rate * rf) / (rf - 1);
  }

  function amortSummary(loan, rateAnnual, termYears, months = 60) {
    const r = rateAnnual / 12;
    const n = termYears * 12;
    const pay = -pmt(r, n, loan);
    let bal = loan;
    let interestSum = 0;
    for (let m = 1; m <= months; m++) {
      const int = bal * r;
      const princ = Math.min(pay - int, bal);
      bal = Math.max(0, bal - princ);
      interestSum += int;
    }
    return { monthlyPI: pay, interest60: interestSum };
  }

  function computeSideFromValues(v) {
    const L = num(v.amount);
    const rate = pct(v.rate);
    const years = Math.max(1, Math.round(num(v.term) || 30));

    const pointsPct = pct(v.points);
    const pointsCost = L * pointsPct;
    const lenderFees = num(v.lender_fees);
    const credits = num(v.credits);
    const shop = num(v.shop_total);
    const other3p = num(v.other_3p);
    const prepaids = num(v.prepaids);
    const taxesInsMo = num(v.taxes_ins);
    const pmiMo = num(v.pmi);
    const down = num(v.down);
    const statedCash = num(v.cash_to_close);

    const am = amortSummary(L, rate, years, 60);
    const monthlyPmt = am.monthlyPI + taxesInsMo + pmiMo;
    const cashToClose = statedCash > 0
      ? statedCash
      : pointsCost + lenderFees + shop + other3p + prepaids - credits + down;
    const fiveYearCost = am.interest60 + (pmiMo * 60) + pointsCost + lenderFees + shop + other3p - credits;

    return {
      L, rate, years,
      monthlyPmt, cashToClose, fiveYearCost,
      pointsCost, monthlyPI: am.monthlyPI
    };
  }

  function computeSide(prefix, getEl) {
    const $ = getEl || ((id) => document.getElementById(id));
    return computeSideFromValues({
      amount: $(prefix + '_amount')?.value,
      rate: $(prefix + '_rate')?.value,
      term: $(prefix + '_term')?.value,
      points: $(prefix + '_points')?.value,
      lender_fees: $(prefix + '_lender_fees')?.value,
      credits: $(prefix + '_credits')?.value,
      shop_total: $(prefix + '_shop_total')?.value,
      other_3p: $(prefix + '_other_3p')?.value,
      prepaids: $(prefix + '_prepaids')?.value,
      taxes_ins: $(prefix + '_taxes_ins')?.value,
      pmi: $(prefix + '_pmi')?.value,
      down: $(prefix + '_down')?.value,
      cash_to_close: $(prefix + '_cash_to_close')?.value
    });
  }

  function fmtMoney(v) {
    return isFinite(v)
      ? v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
      : '$—';
  }

  function breakeven(side) {
    if (side.pointsCost <= 0) return 'N/A';
    const altPI = amortSummary(side.L, side.rate + 0.0025, side.years, 1).monthlyPI;
    const save = altPI - side.monthlyPI;
    return save > 0 ? Math.ceil(side.pointsCost / save) + ' mo' : 'N/A';
  }

  function compareSides(A, B) {
    const beA = breakeven(A);
    const beB = breakeven(B);
    let winner = 'N/A';
    if (beA !== 'N/A' && beB !== 'N/A') {
      const a = parseInt(beA, 10);
      const b = parseInt(beB, 10);
      winner = a < b ? 'A' : b < a ? 'B' : 'Tie';
    } else if (beA !== 'N/A') winner = 'A';
    else if (beB !== 'N/A') winner = 'B';

    return {
      monthly: { a: A.monthlyPmt, b: B.monthlyPmt, diff: B.monthlyPmt - A.monthlyPmt },
      cash: { a: A.cashToClose, b: B.cashToClose, diff: B.cashToClose - A.cashToClose },
      fiveYear: { a: A.fiveYearCost, b: B.fiveYearCost, diff: B.fiveYearCost - A.fiveYearCost },
      breakeven: { a: beA, b: beB, winner }
    };
  }

  global.LECompare = {
    num, pct, computeSide, computeSideFromValues, fmtMoney, compareSides, breakeven
  };
})(typeof window !== 'undefined' ? window : global);
