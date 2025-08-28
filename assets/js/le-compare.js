const $ = (id) => document.getElementById(id);

const num = (v) => {
  if (!v) return 0;
  const s = String(v).replace(/[%,$\s]/g, '');
  return s ? parseFloat(s) : 0;
};
const pct = (v) => num(v) / 100;

function pmt(rate, nper, pv) {
  const r = rate;
  if (r === 0) return -(pv / nper);
  const rf = Math.pow(1 + r, nper);
  return -(pv * r * rf) / (rf - 1);
}

function amortSummary(loan, rateAnnual, termYears, months = 60) {
  const r = rateAnnual / 12;
  const n = termYears * 12;
  const pay = -pmt(r, n, loan);
  let bal = loan, interestSum = 0;
  for (let m = 1; m <= months; m++) {
    const int = bal * r;
    const princ = Math.min(pay - int, bal);
    bal = Math.max(0, bal - princ);
    interestSum += int;
  }
  return { monthlyPI: pay, interest60: interestSum };
}

function computeSide(prefix) {
  const L = num($(prefix + '_amount').value);
  const rate = pct($(prefix + '_rate').value);
  const years = Math.max(1, Math.round(num($(prefix + '_term').value) || 30));

  const pointsPct = pct($(prefix + '_points').value);
  const pointsCost = L * pointsPct;
  const lenderFees = num($(prefix + '_lender_fees').value);
  const credits = num($(prefix + '_credits').value);
  const shop = num($(prefix + '_shop_total').value);
  const other3p = num($(prefix + '_other_3p').value);
  const prepaids = num($(prefix + '_prepaids').value);
  const taxesInsMo = num($(prefix + '_taxes_ins').value);
  const pmiMo = num($(prefix + '_pmi').value);
  const down = num($(prefix + '_down').value);

  const am = amortSummary(L, rate, years, 60);
  const monthlyPmt = am.monthlyPI + taxesInsMo + pmiMo;
  const cashToClose = pointsCost + lenderFees + shop + other3p + prepaids - credits + down;
  const fiveYearCost = am.interest60 + (pmiMo * 60) + pointsCost + lenderFees + shop + other3p - credits;

  return {
    L, rate, years,
    monthlyPmt, cashToClose, fiveYearCost,
    pointsCost, monthlyPI: am.monthlyPI
  };
}

function fmtMoney(v) {
  return isFinite(v)
    ? v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : '$—';
}

function compare() {
  const A = computeSide('a');
  const B = computeSide('b');

  // Monthly
  $('resA_monthly').textContent = fmtMoney(A.monthlyPmt);
  $('resB_monthly').textContent = fmtMoney(B.monthlyPmt);
  $('resDiff_monthly').textContent = fmtMoney(B.monthlyPmt - A.monthlyPmt);

  // Cash to close
  $('resA_cash').textContent = fmtMoney(A.cashToClose);
  $('resB_cash').textContent = fmtMoney(B.cashToClose);
  $('resDiff_cash').textContent = fmtMoney(B.cashToClose - A.cashToClose);

  // 5-year
  $('resA_5yr').textContent = fmtMoney(A.fiveYearCost);
  $('resB_5yr').textContent = fmtMoney(B.fiveYearCost);
  $('resDiff_5yr').textContent = fmtMoney(B.fiveYearCost - A.fiveYearCost);

  // Points break-even (rough): estimate monthly PI savings per ~0.25% rate
  function breakeven(side) {
    if (side.pointsCost <= 0) return 'N/A';
    const altPI = amortSummary(side.L, side.rate + 0.0025, side.years, 1).monthlyPI;
    const save = altPI - side.monthlyPI;
    return save > 0 ? Math.ceil(side.pointsCost / save) + ' mo' : 'N/A';
  }
  const beA = breakeven(A);
  const beB = breakeven(B);
  $('resA_breakeven').textContent = beA;
  $('resB_breakeven').textContent = beB;

  let winner = 'N/A';
  if (beA !== 'N/A' && beB !== 'N/A') {
    const a = parseInt(beA), b = parseInt(beB);
    winner = a < b ? 'A' : b < a ? 'B' : 'Tie';
  } else if (beA !== 'N/A') winner = 'A';
  else if (beB !== 'N/A') winner = 'B';
  $('res_breakeven_winner').textContent = winner;
}

function resetAll() {
  ['formA', 'formB'].forEach(id => $(id).reset());
  [
    'resA_monthly','resB_monthly','resDiff_monthly',
    'resA_cash','resB_cash','resDiff_cash',
    'resA_5yr','resB_5yr','resDiff_5yr',
    'resA_breakeven','resB_breakeven','res_breakeven_winner'
  ].forEach(id => $(id).textContent = '—');
}

document.addEventListener('DOMContentLoaded', () => {
  $('compareBtn').addEventListener('click', compare);
  $('resetBtn').addEventListener('click', resetAll);
});