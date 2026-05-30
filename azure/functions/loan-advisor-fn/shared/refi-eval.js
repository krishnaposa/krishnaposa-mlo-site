const { estimateRate, ltvPercent } = require('./rate-pricing');

const DEFAULT_THRESHOLDS = {
  minRateDropPct: 0.50,
  minMonthlySavings: 50,
  goBreakEvenMonths: 36,
  maybeBreakEvenMonths: 48,
  minRateDropForAnyBenefit: 0.125
};

function termYearsFromLabel(term) {
  const m = String(term || '').match(/(\d+)/);
  return m ? Number(m[1]) : 30;
}

function monthlyPI(loanAmt, annualRatePct, years = 30) {
  const n = years * 12;
  const m = (annualRatePct / 100) / 12;
  if (!isFinite(loanAmt) || !isFinite(annualRatePct) || loanAmt <= 0) return NaN;
  if (m === 0) return loanAmt / n;
  const pow = Math.pow(1 + m, n);
  return loanAmt * (m * pow) / (pow - 1);
}

function breakEvenMonths(monthlySavings, closingCosts) {
  if (!isFinite(monthlySavings) || monthlySavings <= 0) return Infinity;
  if (!isFinite(closingCosts) || closingCosts <= 0) return 0;
  return Math.ceil(closingCosts / monthlySavings);
}

function fmtMoney(n) {
  if (!isFinite(n)) return '$—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function fmtRate(n) {
  if (!isFinite(n)) return '—';
  return `${n.toFixed(3)}%`;
}

function evaluateRefi(profile, thresholds = DEFAULT_THRESHOLDS, ratesOverride = null) {
  const loanBalance = Number(profile.loanBalance);
  const currentRate = Number(profile.currentRate);
  const refiCosts = Number(profile.refiCosts ?? 0);
  const stayYears = Number(profile.stayYears ?? 5);
  const yearsRemaining = Number(profile.yearsRemaining ?? termYearsFromLabel(profile.term));
  const newTermYears = termYearsFromLabel(profile.term);
  const homeValue = Number(profile.homeValue);
  const ltv = profile.ltv ?? ltvPercent(homeValue, loanBalance);

  const errors = [];
  if (!loanBalance || loanBalance <= 0) errors.push('loan balance required');
  if (!currentRate || currentRate <= 0) errors.push('current rate required');
  if (!homeValue || homeValue <= 0) errors.push('home value required');
  if (errors.length) return { ok: false, errors };

  const market = ratesOverride || estimateRate({
    term: profile.term || '30 Year Fixed',
    fico: profile.fico,
    ltv,
    occupancy: profile.occupancy || 'Primary Residence',
    propertyType: profile.propertyType || 'Single Family',
    dti: profile.dti ?? 36,
    purpose: profile.purpose || 'Rate/Term Refinance',
    veteran: profile.veteran || 'No'
  });

  const marketRate = market.base;
  const rateDrop = currentRate - marketRate;
  const currentPI = monthlyPI(loanBalance, currentRate, yearsRemaining);
  const newPI = monthlyPI(loanBalance, marketRate, newTermYears);
  const monthlySavings = Math.max(0, currentPI - newPI);
  const beMonths = breakEvenMonths(monthlySavings, refiCosts);
  const stayMonths = Math.max(1, stayYears * 12);

  let verdict = 'NOT_YET';
  const bullets = [];

  bullets.push(
    `Estimated market rate for your profile: ${fmtRate(marketRate)} (range ${fmtRate(market.base)}–${fmtRate(market.high)}). Your current rate: ${fmtRate(currentRate)}.`
  );
  bullets.push(
    `Principal & interest: about ${fmtMoney(currentPI)}/mo now vs ${fmtMoney(newPI)}/mo at the estimated new rate — savings about ${fmtMoney(monthlySavings)}/mo (taxes/insurance/PMI not included).`
  );

  if (refiCosts > 0 && isFinite(beMonths)) {
    bullets.push(
      `Closing costs of ${fmtMoney(refiCosts)} would break even in about ${beMonths} month${beMonths === 1 ? '' : 's'}. You plan to stay ~${stayYears} year${stayYears === 1 ? '' : 's'}.`
    );
  } else if (refiCosts <= 0) {
    bullets.push('No closing costs entered — break-even time depends on your actual lender fees.');
  }

  if (newTermYears > yearsRemaining + 2) {
    bullets.push(
      `Note: a new ${newTermYears}-year loan resets the amortization clock. You have ~${yearsRemaining} years left on your current loan — compare total interest, not just payment.`
    );
  }

  if (rateDrop < thresholds.minRateDropForAnyBenefit || monthlySavings < 1) {
    verdict = 'NO_BENEFIT';
    bullets.push('The estimated rate is not meaningfully below your current rate — refinancing likely would not reduce your payment enough to matter.');
  } else if (rateDrop >= thresholds.minRateDropPct && monthlySavings >= thresholds.minMonthlySavings &&
             beMonths <= thresholds.goBreakEvenMonths && beMonths <= stayMonths) {
    verdict = 'GO';
    bullets.push('Rate drop, monthly savings, and break-even vs your stay timeline look favorable for exploring a refinance.');
  } else if (rateDrop >= thresholds.minRateDropForAnyBenefit && monthlySavings >= thresholds.minMonthlySavings &&
             beMonths <= thresholds.maybeBreakEvenMonths) {
    verdict = 'MAYBE';
    if (beMonths > stayMonths) {
      bullets.push('Savings exist, but break-even may exceed how long you plan to keep the home — run the numbers for your exact timeline.');
    } else if (rateDrop < thresholds.minRateDropPct) {
      bullets.push('Modest rate improvement — worth a quote if closing costs are low or you need cash-flow relief.');
    } else {
      bullets.push('Borderline case — get a formal Loan Estimate before deciding.');
    }
  } else {
    verdict = 'NOT_YET';
    bullets.push('Not enough savings or break-even is too long for your situation right now — check again when rates move or your balance drops.');
  }

  const verdictLabel = {
    GO: 'Worth exploring',
    MAYBE: 'Maybe — get a quote',
    NOT_YET: 'Not yet',
    NO_BENEFIT: 'Unlikely to help'
  }[verdict];

  const summary = verdict === 'GO'
    ? `Refinancing may make sense: ~${fmtMoney(monthlySavings)}/mo savings with break-even around ${beMonths} months.`
    : verdict === 'MAYBE'
      ? `Refinancing is borderline: ~${fmtMoney(monthlySavings)}/mo savings; review costs and how long you will keep the home.`
      : verdict === 'NO_BENEFIT'
        ? `Estimated market rate (${fmtRate(marketRate)}) is close to your current rate (${fmtRate(currentRate)}) — little payment benefit expected.`
        : 'Hold for now — savings or break-even do not clearly justify refinancing yet.';

  return {
    ok: true,
    verdict,
    verdictLabel,
    summary,
    bullets,
    metrics: {
      ltv,
      currentRate,
      marketRate,
      marketRateHigh: market.high,
      rateDrop: Math.round(rateDrop * 1000) / 1000,
      currentPI: Math.round(currentPI),
      newPI: Math.round(newPI),
      monthlySavings: Math.round(monthlySavings),
      breakEvenMonths: isFinite(beMonths) ? beMonths : null,
      stayMonths,
      refiCosts,
      yearsRemaining,
      newTermYears
    },
    rates: market
  };
}

function buildAiPrompt(result, profile) {
  return `Mortgage refinance analysis (educational only):
Profile: ${JSON.stringify({ state: profile.state, occupancy: profile.occupancy, fico: profile.fico, ltv: result.metrics.ltv, stayYears: profile.stayYears })}
Verdict: ${result.verdict} (${result.verdictLabel})
Metrics: ${JSON.stringify(result.metrics)}
Bullets: ${result.bullets.join(' ')}

In 2 short paragraphs, explain in plain English why refinancing ${result.verdict === 'GO' ? 'may' : result.verdict === 'NO_BENEFIT' ? 'likely does not' : 'might or might not'} make sense for this borrower. Mention break-even and stay timeline. End with one caution (costs, extending term, or rate can change). No jargon.`;
}

module.exports = {
  DEFAULT_THRESHOLDS,
  evaluateRefi,
  buildAiPrompt
};
