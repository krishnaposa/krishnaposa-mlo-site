async function callAzureOpenAi(prompt, maxTokens = 320) {
  const azEndpoint = process.env.AZURE_OPENAI_ENDPOINT;
  const azKey = process.env.AZURE_OPENAI_API_KEY || process.env.AZURE_OPENAI_KEY;
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT || 'gpt-4o';
  const apiVer = process.env.AZURE_OPENAI_API_VERSION || '2024-12-01-preview';

  if (!azEndpoint || !azKey) return null;

  const url = `${azEndpoint.replace(/\/$/, '')}/openai/deployments/${deployment}/chat/completions?api-version=${apiVer}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'api-key': azKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [
        { role: 'system', content: 'You are a helpful mortgage loan advisor. Educational only, not a credit decision. Do not promise approval or exact rates.' },
        { role: 'user', content: prompt }
      ],
      max_tokens: maxTokens,
      temperature: 0.4
    })
  });

  if (!res.ok) {
    const errBody = await res.text().catch(() => '');
    console.error('Azure OpenAI error', res.status, errBody.slice(0, 300));
    return null;
  }

  const data = await res.json();
  const text = data.choices?.[0]?.message?.content?.trim();
  return text || null;
}

async function callOpenAiDirect(prompt, maxTokens = 320) {
  const openaiKey = process.env.OPENAI_API_KEY;
  if (!openaiKey) return null;

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${openaiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
      messages: [
        { role: 'system', content: 'You are a helpful mortgage loan advisor. Educational only, not a credit decision.' },
        { role: 'user', content: prompt }
      ],
      max_tokens: maxTokens,
      temperature: 0.4
    })
  });

  if (!res.ok) {
    const errBody = await res.text().catch(() => '');
    console.error('OpenAI error', res.status, errBody.slice(0, 300));
    return null;
  }

  const data = await res.json();
  const text = data.choices?.[0]?.message?.content?.trim();
  return text || null;
}

/** Returns { text, source: 'azure'|'openai'|'fallback' } */
async function callAi(prompt, fallback) {
  let text = await callAzureOpenAi(prompt);
  if (text) return { text, source: 'azure' };

  text = await callOpenAiDirect(prompt);
  if (text) return { text, source: 'openai' };

  return { text: fallback, source: 'fallback' };
}

module.exports = { callAi, callAzureOpenAi, callOpenAiDirect };
