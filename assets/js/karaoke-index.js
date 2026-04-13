/* ===== karaoke-index.js =====
   Upload + poll jobs; when done, dual playback (karaoke-core.js + karaoke-azure.js for API).
*/
(function (w) {
  const K = w.KARAOKE;

  // Elements
  const els = {
    file: K.$('file'),
    go: K.$('go'),
    clear: K.$('clear'),
    status: K.$('status'),
    alert: K.$('alert'),
    done: K.$('done'),
    links: K.$('links'),
    prog: K.$('prog'),
    bar: K.$('bar'),
    playerCard: K.$('playerCard'),

    // lyrics bits (optional on the page)
    lyrJobId: K.$('lyrJobId'),
    lyricsBox: K.$('lyricsBox'),
    lyrText: K.$('lyrText'),
    lyricsMsg: K.$('lyricsMsg'),
    loadLyricsBtn: K.$('loadLyrics'),
    saveLyricsBtn: K.$('saveLyrics'),
  };

  function setStatus(t){ if (els.status) els.status.textContent = t || ''; }
  function showError(msg){ if (els.alert){ els.alert.textContent = msg; els.alert.classList.remove('hide'); } }
  function hideError(){ if (els.alert){ els.alert.classList.add('hide'); els.alert.textContent = ''; } }

  let pollTimer = null;

  // Playback controls from common
  const PB = K.initPlaybackControls({});

  function resetUI() {
    setStatus(''); hideError();
    els.done?.classList.add('hide');
    if (els.links) els.links.innerHTML = '';
    if (els.prog) els.prog.hidden = true;
    if (els.bar) els.bar.style.width = '0%';
    els.playerCard?.classList.add('hide');
    K.setJobId(null);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    if (els.lyricsBox) els.lyricsBox.textContent = '';
    if (els.lyrText)   els.lyrText.value = '';
    if (els.lyricsMsg) els.lyricsMsg.textContent = '';
    if (els.lyrJobId)  els.lyrJobId.value = '';
  }

  els.clear?.addEventListener('click', () => {
    if (els.file) els.file.value = '';
    resetUI();
  });

  // ---- Polling for job status ----
  async function doPoll(jobId) {
    try {
      const r = await fetch(K.endpoints.statusUrl(jobId), { mode:'cors' });
      if (r.status === 404) return;
      const s = await r.json();

      if (s.state === 'queued') {
        setStatus('Queued…'); els.prog && (els.prog.hidden=false);
        if (els.bar && !els.bar.style.width) els.bar.style.width = '10%';
        return;
      }
      if (s.state === 'running') {
        const p = Math.max(10, Math.min(95, s.progress ?? 50));
        els.prog && (els.prog.hidden=false);
        els.bar && (els.bar.style.width = p + '%');
        setStatus(`Processing… (${p}%)`);
        return;
      }
      if (s.state === 'failed') {
        setStatus('Error.');
        const retryTxt = s.retrying ? ` Retrying (attempt ${s.attempt}) in ${s.next_retry_in_seconds}s.` : '';
        showError((s.error || 'Job failed.') + retryTxt);
        if (!s.retrying && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        els.prog && (els.prog.hidden=true); els.bar && (els.bar.style.width='0%');
        return;
      }
      if (s.state === 'done') {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        els.bar && (els.bar.style.width='100%');
        setTimeout(() => { els.prog && (els.prog.hidden=true); els.bar && (els.bar.style.width='0%'); }, 800);
        setStatus('Done!');

        // Persist job id so lyrics load/save work without typing
        K.setJobId(jobId);
        if (els.lyrJobId && !els.lyrJobId.value) els.lyrJobId.value = jobId;

        // Links
        els.done?.classList.remove('hide');
        if (els.links) els.links.innerHTML = '';
        for (const [name, val] of Object.entries(s.outputs || {})) {
          const href = K.asUrl(val);
          if (els.links) {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.textContent = name;
            if (href !== '#') { a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.download = name; }
            li.appendChild(a); els.links.appendChild(li);
          }
        }

        // Set playback sources + title
        const vocalsUrl = (s.outputs || {})['vocals.wav'] || '';
        const bandUrl   = (s.outputs || {})['no_vocals.wav'] || '';
        if (vocalsUrl && bandUrl) {
          PB.setSources(vocalsUrl, bandUrl);
          const base = (s.original_name || '').split('/').pop() || '—';
          PB.showTitle(base.replace(/\.(wav|mp3|m4a|flac|aac)$/i,'') || '—');
          els.playerCard?.classList.remove('hide');
        }
        return;
      }
      setStatus(s.state || '…');
    } catch (e) {
      console.warn('poll error', e);
    }
  }

  function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => doPoll(jobId), 1500);
  }

  // ---- Submit upload ----
  els.go?.addEventListener('click', async () => {
    try{
      hideError(); els.done?.classList.add('hide'); if (els.links) els.links.innerHTML = '';
      setStatus('Submitting…'); els.prog && (els.prog.hidden=false); els.bar && (els.bar.style.width='10%');

      const fd = new FormData();
      if (els.file?.files[0]) fd.append('file', els.file.files[0]);
      if (!fd.has('file')) throw new Error('Please choose a file to upload.');

      const res = await fetch(K.endpoints.submitUrl, { method:'POST', body: fd, mode:'cors' });
      let data = null; try { data = await res.json(); } catch {}
      if (!res.ok) {
        const msg = (data && (data.error || data.message)) || (await res.text());
        throw new Error(msg || `Submit failed (${res.status})`);
      }
      const jobId = data && data.job_id;
      if (!jobId) throw new Error('No job id returned.');

      K.setJobId(jobId);
      if (els.lyrJobId) els.lyrJobId.value = jobId; // mirror in the input for transparency
      (w.dataLayer = w.dataLayer || []).push({ event: 'karaoke_submit' });
      setStatus('Queued. Processing…');
      startPolling(jobId);
    } catch (e) {
      let msg = e.message || String(e);
      const submitUrl = (K.endpoints && K.endpoints.submitUrl) || '';
      const localHttp = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i.test(submitUrl);
      if (localHttp && /failed to fetch|networkerror|load failed/i.test(msg)) {
        msg = 'Could not reach the local queue server at ' + submitUrl + '. ';
        if (location.protocol === 'https:') {
          msg += 'This page is on HTTPS; browsers block calls to http://127.0.0.1 (mixed content). Serve this page over http:// (e.g. python -m http.server from the repo) or use file://. ';
        }
        msg += 'Confirm python karaoke/local_folder_queue.py is running and the port matches ?api= or KARAOKE_API_BASE.';
      }
      showError(msg);
      setStatus(''); els.prog && (els.prog.hidden=true); els.bar && (els.bar.style.width='0%');
    }
  });

  // ---- Lyrics: Load & Save (always pass a job id) ----
  els.loadLyricsBtn?.addEventListener('click', async () => {
    // Prefer the in-memory job id; else, take what user typed
    let jobId = K.currentJobId || (els.lyrJobId?.value || '').trim();
    if (!jobId) {
      els.lyricsMsg && (els.lyricsMsg.textContent = 'Please enter a Job ID first.');
      return;
    }

    const title = (K.$('trackTitle')?.textContent || '').trim();
    const durs = PB.getDurations();

    await K.loadLyrics({
      jobId: jobId,
      title: title && title !== '—' ? title : '',
      artist: (K.$('lyrArtist')?.value || '').trim(),
      duration: Math.round(durs.band || durs.vocals || 0),
      lyricsBoxId: 'lyricsBox',
      msgId: 'lyricsMsg',
      textId: 'lyrText'     // also populate the editor
    });
  });

  els.saveLyricsBtn?.addEventListener('click', async () => {
    let jobId = K.currentJobId || (els.lyrJobId?.value || '').trim();
    if (!jobId) {
      els.lyricsMsg && (els.lyricsMsg.textContent = 'Please enter a Job ID first.');
      return;
    }
    await K.saveLyrics({
      jobId: jobId,
      text: els.lyrText?.value || '',
      msgId: 'lyricsMsg'
    });
  });

})(window);