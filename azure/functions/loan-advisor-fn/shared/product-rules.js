// Educational product fit — not underwriting.

const CONFORMING_LIMIT = 766550;

const FICO_MID = {
  '780+': 800, '760-779': 770, '740-759': 750, '720-739': 730,
  '700-719': 710, '680-699': 690, '660-679': 670, '640-659': 650, '620-639': 630
};

function ficoMid(band) {
  return FICO_MID[band] ?? 700;
}

function recommendProduct({
  occupancy, purpose, loanAmount, ltv, fico, veteran, goals, term
}) {
  const la = Number(loanAmount);
  const ltvPct = Number(ltv) || 0;
  const score = ficoMid(fico);
  const termPick = term || '30 Year Fixed';

  const vaEligible = veteran === 'Yes'
    && occupancy === 'Primary Residence'
    && (purpose === 'Purchase' || String(purpose).includes('Refinance'));

  if (vaEligible) {
    return {
      product: 'VA Fixed',
      term: termPick,
      note: 'Eligible veterans on primary residence often qualify with no down payment and no monthly mortgage insurance.'
    };
  }

  if (occupancy === 'Investment') {
    return {
      product: 'Investment Property Loan',
      term: termPick,
      note: 'Rental and DSCR programs use different guidelines than primary-home financing.'
    };
  }

  if (la > CONFORMING_LIMIT) {
    return {
      product: 'Jumbo Fixed',
      term: goals === 'Pay Off Faster' ? '15 Year Fixed' : termPick,
      note: 'Loan amount is above the standard conforming limit — jumbo underwriting typically applies.'
    };
  }

  const fhaStrong = occupancy === 'Primary Residence' && (
    ltvPct > 96
    || (ltvPct > 90 && score < 680)
    || (score < 640 && purpose === 'Purchase')
  );

  const fhaModerate = occupancy === 'Primary Residence'
    && purpose === 'Purchase'
    && ltvPct > 80
    && score < 700;

  if (fhaStrong || fhaModerate) {
    return {
      product: 'FHA Fixed',
      term: goals === 'Pay Off Faster' ? '15 Year Fixed' : termPick,
      note: 'FHA is often considered with lower down payments or moderate credit, with upfront and monthly mortgage insurance.'
    };
  }

  if (purpose === 'Cash-out Refinance' && goals === 'Max Cash Out' && ltvPct > 80) {
    return {
      product: 'FHA Cash-Out (if eligible)',
      term: termPick,
      note: 'Higher-LTV cash-out may be limited on conventional — FHA has distinct caps and mortgage insurance.'
    };
  }

  if (goals === 'Pay Off Faster') {
    return {
      product: 'Conventional Fixed',
      term: '15 Year Fixed',
      note: 'Shorter term reduces total interest if the higher payment fits your budget.'
    };
  }

  if (goals === 'Lowest Monthly Payment' && /ARM/i.test(termPick)) {
    return {
      product: 'Conventional ARM',
      term: termPick,
      note: 'ARMs can start lower but the rate can change after the initial fixed period.'
    };
  }

  if (goals === 'Lowest Cash to Close' && ltvPct > 80 && score >= 700) {
    return {
      product: 'Conventional Fixed',
      term: termPick,
      note: 'Strong credit may qualify for conventional low-down options; compare MI vs FHA insurance costs.'
    };
  }

  return {
    product: 'Conventional Fixed',
    term: termPick,
    note: ltvPct > 80
      ? 'Private mortgage insurance may apply until you reach roughly 20% equity.'
      : 'Conventional financing often fits strong credit and standard down payment profiles.'
  };
}

module.exports = { CONFORMING_LIMIT, ficoMid, recommendProduct };
