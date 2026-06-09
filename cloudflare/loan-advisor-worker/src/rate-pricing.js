// Rate estimation for purchase / refinance scenarios (educational estimates only).

export const BASE_BY_TERM = {
  '30 Year Fixed': 6.500,
  '20 Year Fixed': 6.300,
  '15 Year Fixed': 6.000,
  '10 Year ARM': 5.950,
  '7 Year ARM': 5.850,
  '5 Year ARM': 5.800
};

const FICO_ADJ = {
  '780+': -0.10, '760-779': -0.05, '740-759': 0.00, '720-739': 0.05,
  '700-719': 0.10, '680-699': 0.20, '660-679': 0.35, '640-659': 0.60, '620-639': 0.80
};

export function ltvPercent(homeValue, loanAmount) {
  const hv = Number(homeValue);
  const la = Number(loanAmount);
  if (!hv || !la || la <= 0 || hv <= 0) return null;
  return Math.round((la / hv) * 100);
}

export function estimateRate({
  term = '30 Year Fixed',
  fico = '740-759',
  ltv = 80,
  occupancy = 'Primary Residence',
  propertyType = 'Single Family',
  dti = 36,
  purpose = 'Rate/Term Refinance',
  veteran = 'No'
}) {
  let rate = BASE_BY_TERM[term] || 6.600;

  const ficoAdj = FICO_ADJ[fico] ?? 0.20;
  const ltvAdj = ltv <= 60 ? -0.10 :
                 ltv <= 75 ? 0.00 :
                 ltv <= 80 ? 0.05 :
                 ltv <= 85 ? 0.15 :
                 ltv <= 90 ? 0.30 : 0.60;

  const occAdj = occupancy === 'Investment' ? 0.75 :
                 occupancy === 'Second Home' ? 0.20 : 0.00;
  const propAdj = propertyType === 'Condo' ? 0.15 :
                  propertyType === 'Multi-Unit (2–4)' ? 0.35 : 0.00;
  const dtiAdj = Number(dti) > 45 ? 0.20 : 0.00;
  const cashAdj = purpose === 'Cash-out Refinance' ? 0.35 : 0.00;

  const vaEligible = veteran === 'Yes'
    && occupancy === 'Primary Residence'
    && (purpose === 'Purchase' || String(purpose).includes('Refinance'));

  if (vaEligible) rate = Math.min(rate, 6.000);

  const mid = rate + ficoAdj + ltvAdj + occAdj + propAdj + dtiAdj + cashAdj;
  return {
    base: Math.max(mid - 0.125, 3.5),
    mid,
    high: mid + 0.125,
    product: vaEligible ? 'VA Fixed' : term
  };
}
