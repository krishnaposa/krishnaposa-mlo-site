async function callAi(prompt, fallback) {
  const openaiKey = process.env.OPENAI_API_KEY;
  if (openaiKey) {
    try {
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
          max_tokens: 280
        })
      });
      if (res.ok) {
        const data = await res.json();
        return data.choices?.[0]?.message?.content?.trim() || fallback;
      }
    } catch (err) {
      console.error('OpenAI error', err);
    }
  }

  const azEndpoint = process.env.AZURE_OPENAI_ENDPOINT;
  const azKey = process.env.AZURE_OPENAI_API_KEY;
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT || 'gpt-4o-mini';
  const apiVer = process.env.AZURE_OPENAI_API_VERSION || '2024-10-21';

  if (azEndpoint && azKey) {
    try {
      const url = `${azEndpoint.replace(/\/$/, '')}/openai/deployments/${deployment}/chat/completions?api-version=${apiVer}`;
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'api-key': azKey,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: 'You are a helpful mortgage loan advisor. Educational only, not a credit decision.' },
            { role: 'user', content: prompt }
          ],
          max_tokens: 280
        })
      });
      if (res.ok) {
        const data = await res.json();
        return data.choices?.[0]?.message?.content?.trim() || fallback;
      }
    } catch (err) {
      console.error('Azure OpenAI error', err);
    }
  }

  return fallback;
}

module.exports = { callAi };
