/**
 * End-to-end test: 2 LEs → leOcr → compare math (compare-two flow)
 * Run: node scripts/test-le-compare-two.mjs
 */

const API = 'https://loan-advisor-func-app-b4etgvgde3eycsb5.eastus2-01.azurewebsites.net/api';

const LE_A = `
LOAN ESTIMATE — ABC Mortgage
Date Issued 05/15/2026
Loan Amount $360,000
Interest Rate 7.125 %
Loan Terms 30 years
Principal & Interest $2,428.00
Estimated Total Monthly Payment $2,850.00
A. Origination Charges $1,995
B. Services You Cannot Shop For $825
C. Services You Can Shop For $2,100
E. Taxes and Other Government Fees $350
F. Prepaids $3,200
G. Initial Escrow Payment at Closing $1,800
Estimated Cash to Close $18,500
Down Payment $90,000
`;

const LE_B = `
LOAN ESTIMATE — XYZ Lending
Date Issued 05/16/2026
Loan Amount $360,000
Interest Rate 6.875 %
Loan Terms 30 years
Principal & Interest $2,364.00
Estimated Total Monthly Payment $2,786.00
A. Origination Charges $2,895
B. Services You Cannot Shop For $925
C. Services You Can Shop For $2,400
E. Taxes and Other Government Fees $350
F. Prepaids $3,400
G. Initial Escrow Payment at Closing $1,900
Estimated Cash to Close $22,800
Down Payment $90,000
`;

const num = (v) => {
  if (v == null || v === '') return 0;
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

function computeSide(fields) {
  const L = num(fields.amount);
  const rate = pct(fields.rate);
  const years = Math.max(1, Math.round(num(fields.term) || 30));
  const pointsCost = L * pct(fields.points);
  const lenderFees = num(fields.lender_fees);
  const credits = num(fields.credits);
  const shop = num(fields.shop_total);
  const other3p = num(fields.other_3p);
  const prepaids = num(fields.prepaids);
  const taxesInsMo = num(fields.taxes_ins);
  const pmiMo = num(fields.pmi);
  const down = num(fields.down);
  const am = amortSummary(L, rate, years, 60);
  return {
    L, rate, years,
    monthlyPmt: am.monthlyPI + taxesInsMo + pmiMo,
    cashToClose: pointsCost + lenderFees + shop + other3p + prepaids - credits + down,
    fiveYearCost: am.interest60 + pmiMo * 60 + pointsCost + lenderFees + shop + other3p - credits,
    monthlyPI: am.monthlyPI
  };
}

function compareSides(A, B) {
  return {
    monthly: { a: A.monthlyPmt, b: B.monthlyPmt, diff: B.monthlyPmt - A.monthlyPmt },
    cash: { a: A.cashToClose, b: B.cashToClose, diff: B.cashToClose - A.cashToClose },
    fiveYear: { a: A.fiveYearCost, b: B.fiveYearCost, diff: B.fiveYearCost - A.fiveYearCost }
  };
}

function fmt(n) {
  return isFinite(n)
    ? n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : '$—';
}

async function ocrLe(label, text) {
  const res = await fetch(`${API}/leOcr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`${label} OCR failed (${res.status}): ${data.error || 'unknown'}`);
  return data.fields;
}

async function main() {
  console.log('=== 2-LE Upload & Compare Test ===\n');
  console.log('API:', API);
  console.log('Mode: compare-two (le-upload.html?mode=compare-two)\n');

  console.log('Step 1: OCR Lender A (ABC Mortgage — higher rate)...');
  const fieldsA = await ocrLe('Lender A', LE_A);
  console.log('  Parsed:', JSON.stringify(fieldsA, null, 2));

  console.log('\nStep 2: OCR Lender B (XYZ Lending — lower rate)...');
  const fieldsB = await ocrLe('Lender B', LE_B);
  console.log('  Parsed:', JSON.stringify(fieldsB, null, 2));

  console.log('\nStep 3: Compare (same math as le-compare-core.js)...');
  const sideA = computeSide(fieldsA);
  const sideB = computeSide(fieldsB);
  const cmp = compareSides(sideA, sideB);

  const cheaperMo = cmp.monthly.diff < 0 ? 'Lender B' : cmp.monthly.diff > 0 ? 'Lender A' : 'Tie';
  const cheaperCash = cmp.cash.diff < 0 ? 'Lender B' : cmp.cash.diff > 0 ? 'Lender A' : 'Tie';

  console.log('\n--- Comparison Results ---');
  console.log('Lender A (ABC):  rate', fieldsA.rate + '%', '| monthly', fmt(sideA.monthlyPmt), '| cash to close', fmt(sideA.cashToClose));
  console.log('Lender B (XYZ):  rate', fieldsB.rate + '%', '| monthly', fmt(sideB.monthlyPmt), '| cash to close', fmt(sideB.cashToClose));
  console.log('');
  console.log('Monthly payment winner:', cheaperMo, `(${fmt(Math.abs(cmp.monthly.diff))}/mo difference)`);
  console.log('Cash to close winner: ', cheaperCash, `(${fmt(Math.abs(cmp.cash.diff))} difference)`);
  console.log('5-year cost diff:     ', fmt(Math.abs(cmp.fiveYear.diff)), cmp.fiveYear.diff < 0 ? 'less for B' : cmp.fiveYear.diff > 0 ? 'less for A' : 'same');

  const ok = fieldsA.amount && fieldsB.amount && fieldsA.rate && fieldsB.rate;
  console.log('\n===', ok ? 'PASS' : 'FAIL', '===');
  process.exit(ok ? 0 : 1);
}

main().catch((err) => {
  console.error('\nERROR:', err.message);
  process.exit(1);
});
