const LE_SCHEMA = `{
  "lender_name": "string or null",
  "amount": number,
  "rate": number,
  "term": number,
  "points": number,
  "lender_fees": number,
  "credits": number,
  "shop_total": number,
  "other_3p": number,
  "prepaids": number,
  "taxes_ins": number,
  "pmi": number,
  "down": number,
  "confidence": "high|medium|low",
  "notes": "short plain-English note about what was unclear"
}`;

function stripCodeFence(s) {
  return String(s || '').replace(/^```json?\s*/i, '').replace(/```\s*$/i, '').trim();
}

function normalizeFields(raw) {
  const n = (v) => {
    if (v === null || v === undefined || v === '') return 0;
    const x = parseFloat(String(v).replace(/[%,$\s,]/g, ''));
    return isFinite(x) ? x : 0;
  };
  return {
    lender_name: raw.lender_name || null,
    amount: n(raw.amount),
    rate: n(raw.rate),
    term: Math.max(1, Math.round(n(raw.term) || 30)),
    points: n(raw.points),
    lender_fees: n(raw.lender_fees),
    credits: Math.abs(n(raw.credits)),
    shop_total: n(raw.shop_total),
    other_3p: n(raw.other_3p),
    prepaids: n(raw.prepaids),
    taxes_ins: n(raw.taxes_ins),
    pmi: n(raw.pmi),
    down: n(raw.down),
    confidence: raw.confidence || 'medium',
    notes: raw.notes || ''
  };
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

  const rate = grab([
    /Interest Rate\s*([\d.]+)\s*%/i,
    /Rate\s*([\d.]+)\s*%/i
  ]);
  const amount = grab([
    /Loan Amount\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
    /Amount Financed\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);
  const monthlyPI = grab([
    /Principal & Interest\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);
  const totalMonthly = grab([
    /Estimated Total Monthly Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);
  const cashToClose = grab([
    /Estimated Cash to Close\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);
  const down = grab([
    /Funds for Borrower\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
    /Down Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
  ]);

  const sectionA = grab([/A\. Origination Charges\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
  const sectionB = grab([/B\. Services You Cannot Shop For\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
  const sectionC = grab([/C\. Services You Can Shop For\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
  const sectionE = grab([/E\. Taxes and Other Government Fees\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
  const sectionF = grab([/F\. Prepaids\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
  const sectionG = grab([/G\. Initial Escrow Payment at Closing\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);

  const taxesIns = totalMonthly && monthlyPI ? Math.max(0, totalMonthly - monthlyPI) : 0;

  return normalizeFields({
    amount,
    rate,
    term: /15[\s-]*Year|15\s*yr/i.test(t) ? 15 : 30,
    points: 0,
    lender_fees: sectionA,
    credits: 0,
    shop_total: sectionC,
    other_3p: sectionB + sectionE,
    prepaids: sectionF + sectionG,
    taxes_ins: taxesIns,
    pmi: 0,
    down,
    confidence: amount && rate ? 'low' : 'low',
    notes: 'Parsed with basic text rules. Please verify all fields before comparing.'
  });
}

async function callAzureOpenAi(messages, maxTokens = 1200) {
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
  const system = `You extract US mortgage Loan Estimate (LE) form fields. Return ONLY valid JSON matching this schema (numbers only, no strings for amounts): ${LE_SCHEMA}. Use 0 when unknown. Rate is annual percent (e.g. 6.75). Points is percent of loan amount. lender_fees is Section A origination minus points. credits is lender credits as positive number. shop_total is Section C. other_3p is Section B + E. prepaids is F + G. taxes_ins is monthly taxes+insurance (from payment breakdown if shown).`;

  const userParts = [
    { type: 'text', text: 'Extract Loan Estimate fields from this document.' }
  ];
  if (text && text.length > 80) {
    userParts.push({ type: 'text', text: `OCR/text content:\n${text.slice(0, 12000)}` });
  }
  if (imageBase64 && mimeType) {
    userParts.push({
      type: 'image_url',
      image_url: { url: `data:${mimeType};base64,${imageBase64}` }
    });
  }

  const raw = await callAzureOpenAi([
    { role: 'system', content: system },
    { role: 'user', content: userParts }
  ]);

  try {
    return normalizeFields(JSON.parse(stripCodeFence(raw)));
  } catch (e) {
    throw new Error('AI returned invalid JSON');
  }
}

async function parseLoanEstimate({ text, imageBase64, mimeType }) {
  const hasText = text && text.length > 40;
  const hasImage = Boolean(imageBase64);

  if (hasText) {
    const quick = parseLoanEstimateText(text);
    if (quick.amount && quick.rate) return quick;
  }

  if (hasImage || (text && text.length > 80)) {
    try {
      return await parseWithAi({ text, imageBase64, mimeType });
    } catch (err) {
      console.error('AI LE parse failed', err);
      if (hasText) return parseLoanEstimateText(text);
    }
  }

  if (hasText) return parseLoanEstimateText(text);

  if (hasImage) {
    throw new Error(
      'Could not read this file automatically. Try a clearer photo, a text-based PDF, or enter numbers manually on the compare page.'
    );
  }
  throw new Error('No readable text or image provided');
}

module.exports = { parseLoanEstimate, parseLoanEstimateText, normalizeFields };
