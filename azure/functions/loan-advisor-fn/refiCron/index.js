const { evaluateRefi } = require('../shared/refi-eval');
const { listWatches, updateWatchVerdict } = require('../shared/refi-watch-store');
const { sendPlainEmail } = require('../shared/email');

module.exports = async function (context, myTimer) {
  let checked = 0;
  let alerted = 0;

  try {
    const watches = await listWatches();

    for (const watch of watches) {
      const result = evaluateRefi(watch.profile);
      if (!result.ok) continue;
      checked += 1;

      const prev = watch.lastVerdict;
      const now = result.verdict;
      await updateWatchVerdict(watch.rowKey, now);

      const shouldAlert = now === 'GO' && prev !== 'GO';
      if (shouldAlert && watch.email) {
        const subject = `Refinance may be worth a look — ${result.verdictLabel}`;
        const text = [
          result.summary,
          '',
          ...result.bullets,
          '',
          'Educational estimate only — not a loan offer. Reply or book a call for a formal quote.',
          'https://www.krishposa.com/refi-monitor.html'
        ].join('\n');

        const sent = await sendPlainEmail({ to: watch.email, subject, text });
        if (sent) alerted += 1;
      }
    }

    context.log(`[refi-cron] checked=${checked} alerted=${alerted}`);
  } catch (err) {
    context.log.error('[refi-cron]', err);
  }
};
