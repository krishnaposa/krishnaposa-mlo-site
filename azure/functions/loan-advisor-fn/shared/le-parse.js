const LE_SCHEMA = `{
  "lender_name": "string or null",
  "amount": number,
  "rate": number,
  "term": number,
  "points": number,
  "section_a": number,
  "section_b": number,
  "section_c": number,
  "section_d": number,
  "section_e": number,
  "section_f": number,
  "section_g": number,
  "section_h": number,
  "section_i": number,
  "section_j": number,
  "lender_fees": number,
  "credits": number,
  "shop_total": number,
  "other_3p": number,
  "prepaids": number,
  "taxes_ins": number,
  "pmi": number,
  "down": number,
  "cash_to_close": number,
  "monthly_pi": number,
  "monthly_total": number,
  "confidence": "high|medium|low",
  "notes": "short plain-English note about what was unclear"
}`;

const AI_SYSTEM = `You extract US CFPB Loan Estimate (LE) data from page 1 (loan terms, payments) and page 2 (Closing Cost Details).
Return ONLY valid JSON matching this schema (numbers only for amounts): ${LE_SCHEMA}

CRITICAL — use SECTION TOTALS from page 2 headers, NOT individual line items:
- section_a = "A. Origination Charges" TOTAL (e.g. $5,520)
- section_b = "B. Services You Cannot Shop For" TOTAL
- section_c = "C. Services You Can Shop For" TOTAL
- section_d = "D. TOTAL LOAN COSTS (A + B + C)" if shown
- section_e = "E. Taxes and Other Government Fees" TOTAL
- section_f = "F. Prepaids" TOTAL
- section_g = "G. Initial Escrow Payment at Closing" TOTAL (0 if blank)
- section_h = "H. Other" TOTAL
- section_i = "I. TOTAL OTHER COSTS (E + F + G + H)" if shown
- section_j = "J. TOTAL CLOSING COSTS" TOTAL
- credits = "Lender Credits" as positive number (e.g. 209 for -$209)
- cash_to_close = "Estimated Cash to Close" from Calculating Cash to Close table
- down = "Down Payment/Funds from Borrower" from that table
- amount = loan amount from page 1
- rate = initial interest rate percent
- monthly_pi = Principal & Interest monthly
- monthly_total = Estimated Total Monthly Payment
- taxes_ins = monthly taxes+insurance+MI (monthly_total minus monthly_pi if needed)

Also set compare rollup fields:
- lender_fees = section_a
- shop_total = section_c
- other_3p = section_b + section_e + section_h
- prepaids = section_f + section_g
Use 0 when unknown.`;

function stripCodeFence(s) {
  return String(s || '').replace(/^```json?\s*/i, '').replace(/```\s*$/i, '').trim();
}

function num(v) {
  if (v === null || v === undefined || v === '') return 0;
  const x = parseFloat(String(v).replace(/[%,$\s,]/g, ''));
  return isFinite(x) ? x : 0;
}

/** Map section totals → compare fields when rollups missing */
function applySectionRollups(raw) {
  const sectionA = num(raw.section_a);
  const sectionB = num(raw.section_b);
  const sectionC = num(raw.section_c);
  const sectionE = num(raw.section_e);
  const sectionF = num(raw.section_f);
  const sectionG = num(raw.section_g);
  const sectionH = num(raw.section_h);

  const lender_fees = sectionA || num(raw.lender_fees);
  const shop_total = sectionC || num(raw.shop_total);
  const other_3p = (sectionB + sectionE + sectionH) || num(raw.other_3p);
  const prepaids = (sectionF + sectionG) || num(raw.prepaids);
  const credits = Math.abs(num(raw.credits));

  let taxes_ins = num(raw.taxes_ins);
  const monthlyPi = num(raw.monthly_pi);
  const monthlyTotal = num(raw.monthly_total);
  if (!taxes_ins && monthlyTotal && monthlyPi) {
    taxes_ins = Math.max(0, monthlyTotal - monthlyPi);
  }

  return {
    lender_fees,
    shop_total,
    other_3p,
    prepaids,
    credits,
    taxes_ins,
    monthly_pi: monthlyPi,
    monthly_total: monthlyTotal
  };
}

function normalizeFields(raw) {
  const rollups = applySectionRollups(raw);
  return {
    lender_name: raw.lender_name || null,
    amount: num(raw.amount),
    rate: num(raw.rate),
    term: Math.max(1, Math.round(num(raw.term) || 30)),
    points: num(raw.points),
    section_a: num(raw.section_a),
    section_b: num(raw.section_b),
    section_c: num(raw.section_c),
    section_d: num(raw.section_d),
    section_e: num(raw.section_e),
    section_f: num(raw.section_f),
    section_g: num(raw.section_g),
    section_h: num(raw.section_h),
    section_i: num(raw.section_i),
    section_j: num(raw.section_j),
    lender_fees: rollups.lender_fees,
    credits: rollups.credits,
    shop_total: rollups.shop_total,
    other_3p: rollups.other_3p,
    prepaids: rollups.prepaids,
    taxes_ins: rollups.taxes_ins,
    pmi: num(raw.pmi),
    down: num(raw.down),
    cash_to_close: num(raw.cash_to_close),
    monthly_pi: rollups.monthly_pi,
    monthly_total: rollups.monthly_total,
    confidence: raw.confidence || 'medium',
    notes: raw.notes || ''
  };
}

function grabSection(t, letter, label) {
  const patterns = [
    new RegExp(`${letter}\\.\\s*${label}\\s*\\$?\\s*([\\d,]+(?:\\.\\d{2})?)`, 'i'),
    new RegExp(`${letter}\\.\\s*[^$\\n]{0,60}\\$?\\s*([\\d,]+(?:\\.\\d{2})?)`, 'i')
  ];
  for (const re of patterns) {
    const m = t.match(re);
    if (m) return parseFloat(m[1].replace(/[,$]/g, ''));
  }
  return 0;
}

/** Regex fallback when AI is unavailable */
function parseLoanEstimateText(text) {
  const t = String(text || '');
  const grab = (patterns) => {
    for (const re of patterns) {
      const m = t.match(re);
      if (m) return parseFloat(m[1].replace(/[,$]/g, ''));
    }
    return 0;
  };

  const sectionA = grabSection(t, 'A', 'Origination Charges');
  const sectionB = grabSection(t, 'B', 'Services You Cannot Shop For');
  const sectionC = grabSection(t, 'C', 'Services You Can Shop For');
  const sectionE = grabSection(t, 'E', 'Taxes and Other Government Fees');
  const sectionF = grabSection(t, 'F', 'Prepaids');
  const sectionG = grabSection(t, 'G', 'Initial Escrow Payment at Closing');
  const sectionH = grabSection(t, 'H', 'Other');
  const sectionJ = grab([
    /J\. TOTAL CLOSING COSTS\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
    /TOTAL CLOSING COSTS\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);
  const credits = grab([
    /Lender Credits\s*-?\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);

  return normalizeFields({
    amount: grab([
      /Loan Amount\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
      /Amount Financed\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
    ]),
    rate: grab([/Interest Rate\s*([\d.]+)\s*%/i, /Initial Interest Rate\s*([\d.]+)\s*%/i]),
    term: /15[\s-]*Year|15\s*yr/i.test(t) ? 15 : 30,
    points: 0,
    section_a: sectionA,
    section_b: sectionB,
    section_c: sectionC,
    section_e: sectionE,
    section_f: sectionF,
    section_g: sectionG,
    section_h: sectionH,
    section_j: sectionJ,
    credits,
    cash_to_close: grab([/Estimated Cash to Close\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]),
    down: grab([
      /Down Payment\/Funds from Borrower\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
      /Down Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
    ]),
    monthly_pi: grab([/Principal & Interest\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]),
    monthly_total: grab([/Estimated Total Monthly Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]),
    confidence: 'low',
    notes: 'Parsed with basic text rules. Please verify section totals before comparing.'
  });
}

async function callAzureOpenAi(messages, maxTokens = 2200) {
  const azEndpoint = process.env.AZURE_OPENAI_ENDPOINT;
  const azKey = process.env.AZURE_OPENAI_API_KEY || process.env.AZURE_OPENAI_KEY;
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT || 'gpt-4o';
  const apiVer = process.env.AZURE_OPENAI_API_VERSION || '2024-12-01-preview';
  if (!azEndpoint || !azKey) return null;

  const url = `${azEndpoint.replace(/\/$/, '')}/openai/deployments/${deployment}/chat/completions?api-version=${apiVer}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'api-key': azKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, max_tokens: maxTokens, temperature: 0.1 })
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Azure OpenAI ${res.status}: ${err.slice(0, 200)}`);
  }
  const data = await res.json();
  return data.choices?.[0]?.message?.content?.trim() || '';
}

async function parseWithAi({ text, imageBase64, mimeType }) {
  const userParts = [
    { type: 'text', text: 'Extract all Loan Estimate fields. Page 2 Closing Cost Details section totals (A through J) are required.' }
  ];
  if (text && text.length > 80) {
    userParts.push({ type: 'text', text: `OCR/text content:\n${text.slice(0, 12000)}` });
  }
  if (imageBase64 && mimeType) {
    userParts.push({
      type: 'image_url',
      image_url: { url: `data:${mimeType};base64,${imageBase64}`, detail: 'high' }
    });
  }

  const raw = await callAzureOpenAi([
    { role: 'system', content: AI_SYSTEM },
    { role: 'user', content: userParts }
  ]);

  try {
    return normalizeFields(JSON.parse(stripCodeFence(raw)));
  } catch (e) {
    throw new Error('AI returned invalid JSON');
  }
}

function emptyManualFields(note) {
  return normalizeFields({
    lender_name: null,
    amount: 0,
    rate: 0,
    term: 30,
    points: 0,
    section_a: 0,
    section_b: 0,
    section_c: 0,
    section_d: 0,
    section_e: 0,
    section_f: 0,
    section_g: 0,
    section_h: 0,
    section_i: 0,
    section_j: 0,
    lender_fees: 0,
    credits: 0,
    shop_total: 0,
    other_3p: 0,
    prepaids: 0,
    taxes_ins: 0,
    pmi: 0,
    down: 0,
    cash_to_close: 0,
    monthly_pi: 0,
    monthly_total: 0,
    confidence: 'low',
    notes: note || 'Enter your Loan Estimate numbers manually in the form.'
  });
}

function fieldsUsable(fields) {
  return fields && (Number(fields.amount) > 0 || Number(fields.rate) > 0 ||
    Number(fields.section_a) > 0 || Number(fields.section_j) > 0);
}

async function parseLoanEstimate({ text, imageBase64, mimeType }) {
  const hasText = text && text.length > 40;
  const hasImage = Boolean(imageBase64);

  if (hasText) {
    const quick = parseLoanEstimateText(text);
    if (fieldsUsable(quick)) return quick;
  }

  if (hasImage || (text && text.length > 80)) {
    try {
      const ai = await parseWithAi({ text, imageBase64, mimeType });
      if (fieldsUsable(ai)) return ai;
    } catch (err) {
      console.error('AI LE parse failed', err);
    }
  }

  if (hasText) {
    const fallback = parseLoanEstimateText(text);
    if (fieldsUsable(fallback)) return fallback;
  }

  if (hasImage || hasText) {
    return emptyManualFields(
      'Automatic read could not extract all numbers. Please type your Loan Estimate values into the form — loan amount, rate, fees, and cash to close.'
    );
  }
  throw new Error('No readable text or image provided');
}

module.exports = {
  parseLoanEstimate,
  parseLoanEstimateText,
  normalizeFields,
  applySectionRollups,
  LE_SCHEMA
};
