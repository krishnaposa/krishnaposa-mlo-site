const $ = (id) => document.getElementById(id);

function updateCashMathHint(prefix) {
  const hint = $(prefix + '_cash_math_hint');
  if (!hint || !window.LECompare) return;
  const side = window.LECompare.computeSide(prefix);
  const d = side.cashToCloseDetail;
  if (!d || d.computed <= 0) {
    hint.hidden = true;
    hint.textContent = '';
    return;
  }
  const fmt = window.LECompare.fmtMoney;
  if (d.stated <= 0) {
    hint.textContent = `Estimated cash: down + closing (${fmt(d.closingCosts)}) + adjustments − seller credits/deposit = ${fmt(d.computed)}`;
    hint.classList.remove('le-cash-math-hint--warn');
    hint.hidden = false;
    return;
  }
  if (d.matches) {
    hint.textContent = `Cash math checks: down + closing (${fmt(d.closingCosts)}) + adjustments − seller credits/deposit = ${fmt(d.computed)}`;
    hint.classList.remove('le-cash-math-hint--warn');
    hint.hidden = false;
  } else {
    hint.textContent = `Cash math mismatch: LE shows ${fmt(d.stated)} but calculated ${fmt(d.computed)} — verify adjustments, deposit, and section J`;
    hint.classList.add('le-cash-math-hint--warn');
    hint.hidden = false;
  }
}

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

  updateCashMathHint('a');
  updateCashMathHint('b');

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
  ['a', 'b'].forEach((prefix) => {
    const hint = $(prefix + '_cash_math_hint');
    if (hint) {
      hint.hidden = true;
      hint.textContent = '';
      hint.classList.remove('le-cash-math-hint--warn');
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  $('compareBtn').addEventListener('click', compare);
  $('resetBtn').addEventListener('click', resetAll);
  ['a', 'b'].forEach((prefix) => {
    $('form' + prefix.toUpperCase())?.addEventListener('input', () => updateCashMathHint(prefix));
  });
});
