// src/loan-advisor.js — Loan advisor + refinance check + optional watch alerts (Cloudflare Worker)

import { estimateRate, ltvPercent, BASE_BY_TERM } from './rate-pricing.js';
import { evaluateRefi, buildAiPrompt } from './refi-eval.js';

function json(body, status = 200, origin = '*') {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'access-control-allow-origin': origin,
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'POST, OPTIONS',
      'access-control-max-age': '86400'
    }
  });
}

function allowOriginFrom(request) {
  const origin = request.headers.get('origin') || '*';
  try {
    if (origin && /krishposa\.com$/i.test(new URL(origin).hostname)) return origin;
  } catch (_) {}
  return 'https://www.krishposa.com';
}

function corsPreflight(allowOrigin) {
  return new Response(null, {
    status: 204,
    headers: {
      'access-control-allow-origin': allowOrigin,
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'POST, OPTIONS',
      'access-control-max-age': '86400'
    }
  });
}

async function callAi(env, prompt, fallback) {
  if (!env.AI_API_KEY) return fallback;
  try {
    const aiRes = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.AI_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        messages: [
          { role: 'system', content: 'You are a helpful mortgage loan advisor. Educational only, not a credit decision.' },
          { role: 'user', content: prompt }
        ],
        max_tokens: 280
      })
    });
    if (aiRes.ok) {
      const aiData = await aiRes.json();
      return aiData.choices?.[0]?.message?.content?.trim() || fallback;
    }
    console.error('AI API error', aiRes.status);
  } catch (err) {
    console.error('AI call failed', err);
  }
  return fallback;
}

async function handleLoanAdvisor(data, env, allowOrigin) {
  const {
    state, occupancy, purpose, propertyType, homeValue, loanAmount,
    fico, dti, term, veteran, goals
  } = data;

  const hv = Number(homeValue);
  const la = Number(loanAmount);
  if (!hv || !la || la <= 0 || hv <= 0) {
    return json({ error: 'Invalid value or loan amount' }, 400, allowOrigin);
  }
  const ltv = ltvPercent(hv, la);

  const rates = estimateRate({
    term, fico, ltv, occupancy, propertyType, dti, purpose, veteran
  });

  const vaEligible = veteran === 'Yes'
    && occupancy === 'Primary Residence'
    && (purpose === 'Purchase' || purpose?.includes('Refinance'));

  const product = vaEligible ? 'VA Fixed' :
    (goals === 'Pay Off Faster' ? '15 Year Fixed' :
      (goals === 'Lowest Monthly Payment' && /ARM/.test(term)) ? term : term);

  let reasoning = 'Based on your credit tier, LTV, occupancy, and goal, this product balances eligibility and cost while aligning with your payment objective.';

  if (env.AI_API_KEY) {
    const prompt = `User profile: ${JSON.stringify({
      state, occupancy, purpose, propertyType, ltv, fico, dti, term, veteran, goals
    })}.
Recommend the best loan type and explain why in 2 short paragraphs, plain English, no jargon.
End with one cautionary note about risks (like rate changes, PMI, or costs).`;
    reasoning = await callAi(env, prompt, reasoning);
  }

  return json({
    metrics: { ltv },
    recommendation: { product, reasoning },
    rates: { base: rates.base, high: rates.high },
    nextSteps: 'If this looks good, start a full application to lock a rate. We will verify income, assets, credit, and property details.'
  }, 200, allowOrigin);
}

async function handleRefiCheck(data, env, allowOrigin) {
  const result = evaluateRefi(data);
  if (!result.ok) {
    return json({ error: result.errors.join('; ') }, 400, allowOrigin);
  }

  let explanation = result.summary;
  if (env.AI_API_KEY) {
    explanation = await callAi(env, buildAiPrompt(result, data), result.summary);
  }

  return json({
    ...result,
    explanation,
    checkedAt: new Date().toISOString(),
    baselineRates: BASE_BY_TERM
  }, 200, allowOrigin);
}

function watchKey(email) {
  return `watch:${String(email).trim().toLowerCase()}`;
}

async function handleRefiWatch(data, env, allowOrigin) {
  if (!env.REFI_KV) {
    return json({ error: 'Rate watch is not configured yet. Use Check Now and save your profile locally.' }, 503, allowOrigin);
  }

  const email = String(data.email || '').trim().toLowerCase();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return json({ error: 'Valid email required for rate alerts' }, 400, allowOrigin);
  }

  const profile = { ...data };
  delete profile.email;
  const result = evaluateRefi(profile);
  if (!result.ok) {
    return json({ error: result.errors.join('; ') }, 400, allowOrigin);
  }

  const record = {
    email,
    profile,
    lastVerdict: result.verdict,
    lastChecked: new Date().toISOString(),
    createdAt: data.createdAt || new Date().toISOString()
  };

  await env.REFI_KV.put(watchKey(email), JSON.stringify(record));

  return json({
    ok: true,
    message: 'You are subscribed to refinance rate checks. We will email you when it looks worth exploring.',
    currentVerdict: result.verdict,
    verdictLabel: result.verdictLabel
  }, 200, allowOrigin);
}

async function sendAlertEmail(env, { to, subject, text }) {
  if (!env.RESEND_API_KEY) {
    console.log('[refi-alert]', to, subject, text);
    return false;
  }

  const recipients = [to];
  if (env.REFI_MLO_EMAIL && env.REFI_MLO_EMAIL !== to) {
    recipients.push(env.REFI_MLO_EMAIL);
  }

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      from: env.REFI_EMAIL_FROM || 'Refi Monitor <alerts@krishposa.com>',
      to: recipients,
      subject,
      text: env.REFI_MLO_EMAIL && env.REFI_MLO_EMAIL !== to
        ? `${text}\n\n—\nWatch profile email: ${to}`
        : text
    })
  });
  return res.ok;
}

async function runScheduledRefiChecks(env) {
  if (!env.REFI_KV) {
    console.log('[refi-cron] REFI_KV not bound — skip');
    return;
  }

  const list = await env.REFI_KV.list({ prefix: 'watch:' });
  let checked = 0;
  let alerted = 0;

  for (const key of list.keys) {
    const raw = await env.REFI_KV.get(key.name);
    if (!raw) continue;
    let record;
    try {
      record = JSON.parse(raw);
    } catch {
      continue;
    }

    const result = evaluateRefi(record.profile);
    if (!result.ok) continue;
    checked += 1;

    const prev = record.lastVerdict;
    const now = result.verdict;
    record.lastVerdict = now;
    record.lastChecked = new Date().toISOString();
    await env.REFI_KV.put(key.name, JSON.stringify(record));

    const shouldAlert = (now === 'GO' && prev !== 'GO') ||
      (now === 'GO' && record.alertOnGo !== false);

    if (shouldAlert && record.email) {
      const subject = `Refinance may be worth a look — ${result.verdictLabel}`;
      const text = [
        result.summary,
        '',
        ...result.bullets,
        '',
        'Educational estimate only — not a loan offer. Reply or book a call for a formal quote.',
        'https://www.krishposa.com/refi-monitor.html'
      ].join('\n');

      const sent = await sendAlertEmail(env, { to: record.email, subject, text });
      if (sent) alerted += 1;
    }
  }

  console.log(`[refi-cron] checked=${checked} alerted=${alerted}`);
}

export default {
  async fetch(request, env) {
    const allowOrigin = allowOriginFrom(request);
    if (request.method === 'OPTIONS') return corsPreflight(allowOrigin);
    if (request.method !== 'POST') return json({ error: 'Method not allowed' }, 405, allowOrigin);

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    let data;
    try {
      data = await request.json();
    } catch {
      return json({ error: 'Invalid JSON body' }, 400, allowOrigin);
    }

    if (path === '/refi-check') return handleRefiCheck(data, env, allowOrigin);
    if (path === '/refi-watch') return handleRefiWatch(data, env, allowOrigin);

    return handleLoanAdvisor(data, env, allowOrigin);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runScheduledRefiChecks(env));
  }
};
