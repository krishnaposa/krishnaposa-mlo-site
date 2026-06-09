/* assets/js/refi-eval.js — browser refi math; baselines match azure/functions/loan-advisor-fn/shared/rate-pricing.js */
(function () {
  const BASE_BY_TERM = {
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

  const DEFAULT_THRESHOLDS = {
    minRateDropPct: 0.50,
    minMonthlySavings: 50,
    goBreakEvenMonths: 36,
    maybeBreakEvenMonths: 48,
    minRateDropForAnyBenefit: 0.125
  };

  function ltvPercent(homeValue, loanAmount) {
    const hv = Number(homeValue);
    const la = Number(loanAmount);
    if (!hv || !la || la <= 0 || hv <= 0) return null;
    return Math.round((la / hv) * 100);
  }

  function estimateRate(opts) {
    const term = opts.term || '30 Year Fixed';
    const fico = opts.fico || '740-759';
    const ltv = opts.ltv ?? 80;
    const occupancy = opts.occupancy || 'Primary Residence';
    const propertyType = opts.propertyType || 'Single Family';
    const dti = opts.dti ?? 36;
    const purpose = opts.purpose || 'Rate/Term Refinance';
    const veteran = opts.veteran || 'No';

    let rate = BASE_BY_TERM[term] || 6.600;
    const ficoAdj = FICO_ADJ[fico] ?? 0.20;
    const ltvAdj = ltv <= 60 ? -0.10 : ltv <= 75 ? 0.00 : ltv <= 80 ? 0.05 :
                   ltv <= 85 ? 0.15 : ltv <= 90 ? 0.30 : 0.60;
    const occAdj = occupancy === 'Investment' ? 0.75 : occupancy === 'Second Home' ? 0.20 : 0.00;
    const propAdj = propertyType === 'Condo' ? 0.15 : propertyType === 'Multi-Unit (2–4)' ? 0.35 : 0.00;
    const dtiAdj = Number(dti) > 45 ? 0.20 : 0.00;
    const cashAdj = purpose === 'Cash-out Refinance' ? 0.35 : 0.00;
    const vaEligible = veteran === 'Yes' && occupancy === 'Primary Residence' &&
      (purpose === 'Purchase' || String(purpose).includes('Refinance'));
    if (vaEligible) rate = Math.min(rate, 6.000);

    const mid = rate + ficoAdj + ltvAdj + occAdj + propAdj + dtiAdj + cashAdj;
    return {
      base: Math.max(mid - 0.125, 3.5),
      mid,
      high: mid + 0.125,
      product: vaEligible ? 'VA Fixed' : term
    };
  }

  function termYearsFromLabel(term) {
    const m = String(term || '').match(/(\d+)/);
    return m ? Number(m[1]) : 30;
  }

  function monthlyPI(loanAmt, annualRatePct, years) {
    years = years || 30;
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
    return n.toFixed(3) + '%';
  }

  function evaluateRefi(profile, thresholds, ratesOverride) {
    thresholds = thresholds || DEFAULT_THRESHOLDS;
    const loanBalance = Number(profile.loanBalance);
    const currentRate = Number(profile.currentRate);
    const refiCosts = Number(profile.refiCosts ?? 0);
    const stayYears = Number(profile.stayYears ?? 5);
    const yearsRemaining = Number(profile.yearsRemaining ?? termYearsFromLabel(profile.term));
    const newTermYears = termYearsFromLabel(profile.term);
    const homeValue = Number(profile.homeValue);
    const ltv = profile.ltv != null ? profile.ltv : ltvPercent(homeValue, loanBalance);

    const errors = [];
    if (!loanBalance || loanBalance <= 0) errors.push('loan balance required');
    if (!currentRate || currentRate <= 0) errors.push('current rate required');
    if (!homeValue || homeValue <= 0) errors.push('home value required');
    if (errors.length) return { ok: false, errors: errors };

    const market = ratesOverride || estimateRate({
      term: profile.term || '30 Year Fixed',
      fico: profile.fico,
      ltv: ltv,
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
      'Estimated market rate for your profile: ' + fmtRate(marketRate) +
      ' (range ' + fmtRate(market.base) + '-' + fmtRate(market.high) + '). Your current rate: ' + fmtRate(currentRate) + '.'
    );
    bullets.push(
      'Principal & interest: about ' + fmtMoney(currentPI) + '/mo now vs ' + fmtMoney(newPI) +
      '/mo at the estimated new rate — savings about ' + fmtMoney(monthlySavings) + '/mo (taxes/insurance/PMI not included).'
    );

    if (refiCosts > 0 && isFinite(beMonths)) {
      bullets.push(
        'Closing costs of ' + fmtMoney(refiCosts) + ' would break even in about ' + beMonths +
        ' month' + (beMonths === 1 ? '' : 's') + '. You plan to stay ~' + stayYears + ' year' + (stayYears === 1 ? '' : 's') + '.'
      );
    } else if (refiCosts <= 0) {
      bullets.push('No closing costs entered — break-even time depends on your actual lender fees.');
    }

    if (newTermYears > yearsRemaining + 2) {
      bullets.push(
        'Note: a new ' + newTermYears + '-year loan resets the amortization clock. You have ~' +
        yearsRemaining + ' years left on your current loan — compare total interest, not just payment.'
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

    const verdictLabel = { GO: 'Worth exploring', MAYBE: 'Maybe — get a quote', NOT_YET: 'Not yet', NO_BENEFIT: 'Unlikely to help' }[verdict];

    const summary = verdict === 'GO'
      ? 'Refinancing may make sense: ~' + fmtMoney(monthlySavings) + '/mo savings with break-even around ' + beMonths + ' months.'
      : verdict === 'MAYBE'
        ? 'Refinancing is borderline: ~' + fmtMoney(monthlySavings) + '/mo savings; review costs and how long you will keep the home.'
        : verdict === 'NO_BENEFIT'
          ? 'Estimated market rate (' + fmtRate(marketRate) + ') is close to your current rate (' + fmtRate(currentRate) + ') — little payment benefit expected.'
          : 'Hold for now — savings or break-even do not clearly justify refinancing yet.';

    return {
      ok: true,
      verdict: verdict,
      verdictLabel: verdictLabel,
      summary: summary,
      bullets: bullets,
      metrics: {
        ltv: ltv,
        currentRate: currentRate,
        marketRate: marketRate,
        marketRateHigh: market.high,
        rateDrop: Math.round(rateDrop * 1000) / 1000,
        currentPI: Math.round(currentPI),
        newPI: Math.round(newPI),
        monthlySavings: Math.round(monthlySavings),
        breakEvenMonths: isFinite(beMonths) ? beMonths : null,
        stayMonths: stayMonths,
        refiCosts: refiCosts,
        yearsRemaining: yearsRemaining,
        newTermYears: newTermYears
      },
      rates: market
    };
  }

  window.RefiEval = {
    BASE_BY_TERM: BASE_BY_TERM,
    DEFAULT_THRESHOLDS: DEFAULT_THRESHOLDS,
    ltvPercent: ltvPercent,
    estimateRate: estimateRate,
    termYearsFromLabel: termYearsFromLabel,
    monthlyPI: monthlyPI,
    breakEvenMonths: breakEvenMonths,
    fmtMoney: fmtMoney,
    fmtRate: fmtRate,
    evaluateRefi: evaluateRefi
  };
})();
