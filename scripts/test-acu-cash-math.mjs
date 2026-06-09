/**
 * Verify ACU LE cash-to-close math (loanestimate_ACU.pdf OCR values).
 * Run: node scripts/test-acu-cash-math.mjs
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const corePath = join(__dirname, '../assets/js/le-compare-core.js');
const coreSrc = readFileSync(corePath, 'utf8');
const fn = new Function(coreSrc + '; return LECompare;');
const LECompare = fn();

const ACU = {
  amount: 900000,
  rate: 5.125,
  term: 30,
  points: 0,
  section_j: 18201,
  lender_fees: 5520,
  credits: 209,
  shop_total: 3000,
  other_3p: 1608 + 1438 + 856,
  prepaids: 5988,
  down: 458000,
  adjustments_other: 46080,
  seller_credits: 0,
  deposit: 0,
  closing_costs_financed: 0,
  funds_for_borrower: 0,
  cash_to_close: 522281
};

const cash = LECompare.computeCashToClose(ACU);
const side = LECompare.computeSideFromValues(ACU);

console.log('=== ACU Cash-to-Close Math Check ===\n');
console.log('Down payment:        ', ACU.down.toLocaleString());
console.log('Section J (closing): ', ACU.section_j.toLocaleString());
console.log('Adjustments & other: ', ACU.adjustments_other.toLocaleString());
console.log('Lender credits:      ', ACU.credits, '(already net in section J)');
console.log('');
console.log('Computed cash:       ', cash.computed.toLocaleString());
console.log('Stated on LE:        ', cash.stated.toLocaleString());
console.log('Difference:          ', Math.abs(cash.computed - cash.stated));
console.log('Math matches LE:     ', cash.matches ? 'YES' : 'NO');
console.log('');
console.log('Compare uses:        ', side.cashToClose.toLocaleString());

const ok = cash.matches && side.cashToClose === ACU.cash_to_close;
console.log('\n===', ok ? 'PASS' : 'FAIL', '===');
process.exit(ok ? 0 : 1);
