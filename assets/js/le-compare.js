const $ = (id) => document.getElementById(id);

function compare() {
  const A = window.LECompare.computeSide('a');
  const B = window.LECompare.computeSide('b');
  const res = window.LECompare.compareSides(A, B);
  const fmt = window.LECompare.fmtMoney;

  $('resA_monthly').textContent = fmt(res.monthly.a);
  $('resB_monthly').textContent = fmt(res.monthly.b);
  $('resDiff_monthly').textContent = fmt(res.monthly.diff);

  $('resA_cash').textContent = fmt(res.cash.a);
  $('resB_cash').textContent = fmt(res.cash.b);
  $('resDiff_cash').textContent = fmt(res.cash.diff);

  $('resA_5yr').textContent = fmt(res.fiveYear.a);
  $('resB_5yr').textContent = fmt(res.fiveYear.b);
  $('resDiff_5yr').textContent = fmt(res.fiveYear.diff);

  $('resA_breakeven').textContent = res.breakeven.a;
  $('resB_breakeven').textContent = res.breakeven.b;
  $('res_breakeven_winner').textContent = res.breakeven.winner;

  if (typeof window !== 'undefined' && window.innerWidth < 1024) {
    const results = document.getElementById('le-compare-results');
    if (results) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function resetAll() {
  ['formA', 'formB'].forEach((id) => $(id).reset());
  [
    'resA_monthly', 'resB_monthly', 'resDiff_monthly',
    'resA_cash', 'resB_cash', 'resDiff_cash',
    'resA_5yr', 'resB_5yr', 'resDiff_5yr',
    'resA_breakeven', 'resB_breakeven', 'res_breakeven_winner'
  ].forEach((id) => { $(id).textContent = '—'; });
}

document.addEventListener('DOMContentLoaded', () => {
  $('compareBtn').addEventListener('click', compare);
  $('resetBtn').addEventListener('click', resetAll);
});
