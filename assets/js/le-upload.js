/* Loan Estimate upload → OCR → compare or save for review */
(function () {
  const $ = (id) => document.getElementById(id);
  const API = () => (window.LoanApi && window.LoanApi.base) || '';

  const FIELD_IDS = [
    'amount', 'rate', 'term', 'points', 'lender_fees', 'credits',
    'shop_total', 'other_3p', 'prepaids', 'taxes_ins', 'pmi', 'down'
  ];

  const MODE = {
    VS_OURS: 'vs-ours',
    COMPARE_TWO: 'compare-two'
  };

  let currentMode = MODE.COMPARE_TWO;
  let lastUploadMeta = { fileName: '', lenderName: '' };
  let lastExtractedText = '';

  const LABELS = {
    [MODE.VS_OURS]: { a: 'Your current quote', b: 'Our quote' },
    [MODE.COMPARE_TWO]: { a: 'Lender A', b: 'Lender B' }
  };

  function getModeFromUrl() {
    const p = new URLSearchParams(window.location.search).get('mode');
    if (p === MODE.VS_OURS) return MODE.VS_OURS;
    if (p === MODE.COMPARE_TWO) return MODE.COMPARE_TWO;
    return null;
  }

  function switchMode(mode, scroll) {
    const url = new URL(window.location.href);
    url.searchParams.set('mode', mode);
    history.replaceState(null, '', url.pathname + url.search);
    setModeUI(mode);
    if (scroll) {
      ($('leWorkflow') || $('le-upload-section'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function showWorkflow(show) {
    document.querySelectorAll('.le-workflow').forEach((el) => {
      if (el.id === 'leReviewSuccess' || el.id === 'le-compare-results') return;
      el.hidden = !show;
    });
  }

  function getFieldsFromForm(prefix) {
    const out = {};
    FIELD_IDS.forEach((key) => {
      const el = $(prefix + '_' + key);
      if (el) out[key] = el.value;
    });
    return out;
  }

  function setModeUI(mode) {
    if (!mode) {
      document.body.dataset.leMode = '';
      showWorkflow(false);
      $('leModePickerSection')?.classList.remove('le-mode-picker--compact');
      if ($('leHeroTitle')) $('leHeroTitle').textContent = 'Loan Estimate Tools';
      if ($('leHeroLead')) {
        $('leHeroLead').textContent = 'Choose whether you have one quote to review or two quotes to compare side by side.';
      }
      document.querySelectorAll('.le-mode-card').forEach((btn) => {
        btn.classList.remove('le-mode-card--active');
        btn.setAttribute('aria-selected', 'false');
      });
      return;
    }

    currentMode = mode;
    const labels = LABELS[mode];
    const isReview = mode === MODE.VS_OURS;

    document.body.dataset.leMode = mode;
    showWorkflow(true);
    $('leModePickerSection')?.classList.add('le-mode-picker--compact');

    document.querySelectorAll('.le-mode-card').forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle('le-mode-card--active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    const activeLabel = $('leModeActiveLabel');
    if (activeLabel) {
      activeLabel.innerHTML = isReview
        ? '<strong>1 Loan Estimate</strong> — I\'ll compete. Upload yours, verify the numbers, submit — Krish prepares a competitive quote. <button type="button" class="le-switch-mode" data-switch="compare-two">Switch to 2-LE compare</button>'
        : '<strong>2 Loan Estimates</strong> — head-to-head compare. Upload both lenders, then run the comparison. <button type="button" class="le-switch-mode" data-switch="vs-ours">Switch to 1-LE review</button>';
    }

    if ($('leHeroTitle')) {
      $('leHeroTitle').textContent = isReview
        ? 'Send Your LE — I\'ll Compete'
        : 'Compare Two Loan Estimates';
    }

    const heroLead = $('leHeroLead');
    if (heroLead) {
      heroLead.textContent = isReview
        ? 'Send the Loan Estimate you already have. We extract the numbers so you can confirm them, then save your file for review. Krish will follow up with a competitive quote — I\'ll compete.'
        : 'Upload both Loan Estimate PDFs or photos. Fix any OCR numbers, then compare monthly payment, cash to close, and 5-year cost instantly.';
    }

    const zones = $('leUploadZones');
    if (zones) zones.classList.toggle('le-upload-zones--single', isReview);

    const privacy = $('lePrivacyNote');
    if (privacy) {
      privacy.textContent = isReview
        ? 'Your LE is processed securely for OCR, then saved when you submit. Krish follows up with a competitive quote — not an instant comparison.'
        : 'Files are sent securely for OCR only. Verify all numbers, then click Compare Estimates.';
    }

    if ($('titleA')) $('titleA').textContent = isReview ? 'Your Loan Estimate' : 'Lender A — extracted fields';
    if ($('titleB')) $('titleB').textContent = 'Lender B — extracted fields';

    const zoneA = $('zoneA');
    if (zoneA) zoneA.querySelector('strong').textContent = isReview ? 'Your Loan Estimate' : 'Lender A';

    const zoneB = $('zoneB');
    if (zoneB) zoneB.hidden = isReview;

    const lenderBCard = $('lenderBCard');
    if (lenderBCard) lenderBCard.hidden = isReview;

    const reviewPanel = $('leReviewPanel');
    if (reviewPanel) {
      if (!isReview) {
        reviewPanel.hidden = true;
      } else {
        const hasData = $('a_amount')?.value || $('a_rate')?.value;
        reviewPanel.hidden = !hasData;
      }
    }

    const compareActions = $('compareActions');
    if (compareActions) compareActions.hidden = isReview;

    const reviewAside = $('reviewAside');
    if (reviewAside) reviewAside.hidden = !isReview;

    const step1 = $('step1Text');
    if (step1) step1.textContent = isReview ? 'Your LE' : 'PDF or photo for each lender';
    if ($('step2Text')) $('step2Text').textContent = isReview ? 'Verify OCR fields' : 'Edit any OCR fields';
    if ($('step3Text')) $('step3Text').textContent = isReview ? 'Submit for our quote' : 'See payment, cash, 5-yr cost';

    document.querySelectorAll('[data-label-a]').forEach((el) => { el.textContent = labels.a; });
    document.querySelectorAll('[data-label-b]').forEach((el) => { el.textContent = labels.b; });

    if ($('leReviewSuccess')) $('leReviewSuccess').hidden = true;
    if ($('le-compare-results')) $('le-compare-results').hidden = true;
  }

  function showReviewPanel() {
    const panel = $('leReviewPanel');
    if (panel) {
      panel.hidden = false;
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function initPdfJs() {
    if (!window.pdfjsLib) return null;
    window.pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    return window.pdfjsLib;
  }

  async function extractPdfText(file) {
    const pdfjsLib = initPdfJs();
    if (!pdfjsLib) return '';
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    let text = '';
    for (let p = 1; p <= Math.min(pdf.numPages, 3); p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      text += content.items.map((it) => it.str).join(' ') + '\n';
    }
    return text;
  }

  async function pdfPageToCanvas(pdf, pageNum, scale) {
    const page = await pdf.getPage(pageNum);
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
    return canvas;
  }

  async function pdfToCompositeImage(file, maxPages = 2) {
    const pdfjsLib = initPdfJs();
    if (!pdfjsLib) return '';
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    const pages = Math.min(pdf.numPages, maxPages);
    const scale = 1.75;
    const canvases = [];
    for (let p = 1; p <= pages; p++) canvases.push(await pdfPageToCanvas(pdf, p, scale));

    const width = Math.max(...canvases.map((c) => c.width));
    const height = canvases.reduce((sum, c) => sum + c.height, 0);
    const out = document.createElement('canvas');
    out.width = width;
    out.height = height;
    const ctx = out.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, width, height);
    let y = 0;
    canvases.forEach((c) => {
      ctx.drawImage(c, 0, y);
      y += c.height;
    });
    return out.toDataURL('image/jpeg', 0.82).split(',')[1] || '';
  }

  function compressImageBase64(base64, mimeType, maxWidth = 1400) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxWidth / img.width);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve({
          base64: canvas.toDataURL('image/jpeg', 0.82).split(',')[1] || base64,
          mimeType: 'image/jpeg'
        });
      };
      img.onerror = () => resolve({ base64, mimeType });
      img.src = `data:${mimeType || 'image/jpeg'};base64,${base64}`;
    });
  }

  /** Browser-side regex fallback (matches server le-parse.js) */
  function parseTextLocally(text) {
    const t = String(text || '');
    const grab = (patterns) => {
      for (const re of patterns) {
        const m = t.match(re);
        if (m) return parseFloat(m[1].replace(/[,$]/g, ''));
      }
      return 0;
    };
    const rate = grab([/Interest Rate\s*([\d.]+)\s*%/i, /Rate\s*([\d.]+)\s*%/i]);
    const amount = grab([
      /Loan Amount\s*\$?\s*([\d,]+(?:\.\d{2})?)/i,
      /Amount Financed\s*\$?\s*([\d,]+(?:\.\d{2})?)/i
    ]);
    const monthlyPI = grab([/Principal & Interest\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const totalMonthly = grab([/Estimated Total Monthly Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionA = grab([/A\. Origination Charges\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionB = grab([/B\. Services You Cannot Shop For\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionC = grab([/C\. Services You Can Shop For\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionE = grab([/E\. Taxes and Other Government Fees\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionF = grab([/F\. Prepaids\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const sectionG = grab([/G\. Initial Escrow Payment at Closing\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]);
    const taxesIns = totalMonthly && monthlyPI ? Math.max(0, totalMonthly - monthlyPI) : 0;
    return {
      lender_name: null,
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
      down: grab([/Down Payment\s*\$?\s*([\d,]+(?:\.\d{2})?)/i]),
      confidence: amount && rate ? 'low' : 'low',
      notes: 'Parsed locally from PDF text. Please verify all fields.'
    };
  }

  function fieldsUsable(fields) {
    return fields && (Number(fields.amount) > 0 || Number(fields.rate) > 0);
  }

  async function readFileContent(file) {
    let text = '';
    let imageBase64 = '';
    let mimeType = file.type || 'application/octet-stream';

    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
      text = await extractPdfText(file);
      lastExtractedText = text;
      try {
        imageBase64 = await pdfToCompositeImage(file, 2);
        mimeType = 'image/jpeg';
      } catch (e) {
        console.warn('PDF rasterize failed', e);
      }
    } else if (file.type.startsWith('image/')) {
      imageBase64 = await fileToBase64(file);
      lastExtractedText = '';
    } else {
      throw new Error('Upload a PDF or image (JPG, PNG)');
    }

    if (imageBase64) {
      const compressed = await compressImageBase64(imageBase64, mimeType);
      imageBase64 = compressed.base64;
      mimeType = compressed.mimeType;
    }
    return { text, imageBase64, mimeType };
  }

  async function ocrLoanEstimate(file) {
    const payload = await readFileContent(file);
    const base = API();
    if (!base) throw new Error('Loan API not configured');
    const res = await fetch(base + '/leOcr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `OCR request failed (HTTP ${res.status})`);
    return data;
  }

  function fillForm(prefix, fields) {
    FIELD_IDS.forEach((key) => {
      const el = $(prefix + '_' + key);
      if (!el || fields[key] === undefined) return;
      el.value = fields[key];
    });
    const status = $(prefix + '_status');
    if (status) {
      const conf = fields.confidence || 'medium';
      status.textContent = fields.lender_name
        ? `${fields.lender_name} · ${conf} confidence`
        : `Parsed · ${conf} confidence`;
      status.className = 'le-upload-status le-upload-status--' + conf;
    }
    const notes = $(prefix + '_notes');
    if (notes) notes.textContent = fields.notes || '';
  }

  function renderResults(res) {
    const fmt = window.LECompare.fmtMoney;
    const labels = LABELS[currentMode];

    $('resA_monthly').textContent = fmt(res.monthly.a);
    $('resB_monthly').textContent = fmt(res.monthly.b);
    $('resDiff_monthly').textContent = fmt(res.monthly.diff);
    $('resA_cash').textContent = fmt(res.cash.a);
    $('resB_cash').textContent = fmt(res.cash.b);
    $('resDiff_cash').textContent = fmt(res.cash.diff);
    $('resA_5yr').textContent = fmt(res.fiveYear.a);
    $('resB_5yr').textContent = fmt(res.fiveYear.b);
    $('resDiff_5yr').textContent = fmt(res.fiveYear.diff);
    $('resA_breakeven').textContent = res.breakeven.a;
    $('resB_breakeven').textContent = res.breakeven.b;
    $('res_breakeven_winner').textContent = res.breakeven.winner;

    const summary = $('compare_summary');
    if (summary) {
      const cheaperMo = res.monthly.diff < 0 ? labels.b : res.monthly.diff > 0 ? labels.a : 'tie';
      const cheaperCash = res.cash.diff < 0 ? labels.b : res.cash.diff > 0 ? labels.a : 'tie';
      summary.innerHTML =
        `<p><strong>Monthly payment:</strong> ${cheaperMo === 'tie' ? 'Both are similar' : cheaperMo + ' is lower'} (${fmt(Math.abs(res.monthly.diff))}/mo difference).</p>` +
        `<p><strong>Cash to close:</strong> ${cheaperCash === 'tie' ? 'Both are similar' : cheaperCash + ' needs less cash'} (${fmt(Math.abs(res.cash.diff))} difference).</p>` +
        `<p><strong>5-year cost:</strong> ${fmt(Math.abs(res.fiveYear.diff))} ${res.fiveYear.diff < 0 ? 'less for ' + labels.b : res.fiveYear.diff > 0 ? 'less for ' + labels.a : 'same'} over 5 years.</p>`;
    }
    $('le-compare-results').hidden = false;
    $('le-compare-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function runCompare() {
    renderResults(window.LECompare.compareSides(
      window.LECompare.computeSide('a'),
      window.LECompare.computeSide('b')
    ));
  }

  async function submitForReview() {
    const msg = $('leReviewMsg');
    const btn = $('leReviewSubmitBtn');
    const name = $('leReviewName')?.value?.trim();
    const email = $('leReviewEmail')?.value?.trim();
    const phone = $('leReviewPhone')?.value?.trim();
    const notes = $('leReviewNotes')?.value?.trim();

    if (!name || !email) {
      if (msg) msg.textContent = 'Please enter your name and email.';
      return;
    }

    const fields = getFieldsFromForm('a');
    if (!fields.amount && !fields.rate) {
      if (msg) msg.textContent = 'Upload your Loan Estimate first.';
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    if (msg) msg.textContent = '';

    try {
      const base = API();
      const res = await fetch(base + '/leReviewSubmit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contact: { name, email, phone },
          fields,
          fileName: lastUploadMeta.fileName,
          lenderName: lastUploadMeta.lenderName,
          notes,
          source: new URLSearchParams(window.location.search).get('from') === 'home' ? 'homepage' : 'le-upload'
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || 'Could not save review request');

      document.querySelectorAll('.le-workflow').forEach((el) => { el.hidden = true; });
      const success = $('leReviewSuccess');
      if (success) {
        success.hidden = false;
        $('leReviewSuccessMsg').textContent = data.message || 'Saved! Krish will follow up with a competitive quote.';
        success.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (err) {
      if (msg) msg.textContent = err.message || 'Something went wrong. Please call or text 678-481-8252.';
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Submit for review'; }
    }
  }

  async function handleUpload(side, file) {
    const zone = $('zone' + side);
    const label = $('zone' + side + '_label');
    if (zone) zone.classList.add('le-upload-zone--loading');
    if (label) label.textContent = 'Reading ' + file.name + '…';

    try {
      let fields;
      try {
        ({ fields } = await ocrLoanEstimate(file));
      } catch (ocrErr) {
        const local = parseTextLocally(lastExtractedText);
        if (fieldsUsable(local)) {
          fields = local;
          fields.notes = (local.notes || '') + ' Server OCR unavailable — verify every field.';
        } else {
          throw ocrErr;
        }
      }

      fillForm(side.toLowerCase(), fields);
      const needsManual = !fieldsUsable(fields);
      const partial = needsManual || fields.confidence === 'low' || (fields.notes && /verify|manually|automatic read/i.test(fields.notes));
      if (label) {
        label.textContent = needsManual
          ? file.name + ' — enter numbers below'
          : partial ? file.name + ' ✓ (verify fields)' : file.name + ' ✓';
      }
      if (needsManual) {
        alert('We could not auto-read every number from this file. Please type your Loan Estimate values into the form below, then submit for review.');
      }

      if (side === 'A') {
        lastUploadMeta = {
          fileName: file.name,
          lenderName: fields.lender_name || ''
        };
      }

      if (currentMode === MODE.VS_OURS && side === 'A') {
        showReviewPanel();
      }
      if (partial) {
        ($('leWorkflow') || $('le-upload-section'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (err) {
      const msg = String(err.message || '');
      const local = parseTextLocally(lastExtractedText);
      if (fieldsUsable(local)) {
        fillForm(side.toLowerCase(), local);
        if (label) label.textContent = file.name + ' ✓ (enter missing fields)';
        if (side === 'A') {
          lastUploadMeta = { fileName: file.name, lenderName: local.lender_name || '' };
        }
        if (currentMode === MODE.VS_OURS && side === 'A') showReviewPanel();
        ($('leWorkflow') || $('le-upload-section'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        alert('We could only read part of your file. The form is pre-filled where possible — please enter or fix any missing numbers, then submit.');
        return;
      }
      const friendly = /failed to fetch|networkerror|load failed/i.test(msg)
        ? 'Upload could not reach the server. Refresh and try again.'
        : /text-based pdf|could not read/i.test(msg)
          ? 'Automatic read did not work for this file. You can still type your LE numbers into the form below — no need to re-upload.'
          : (msg || 'Could not read Loan Estimate');
      if (label) label.textContent = 'Upload failed — enter numbers manually';
      showWorkflow(true);
      if (currentMode === MODE.VS_OURS && side === 'A') showReviewPanel();
      ($('le-upload-section') || $('leWorkflow'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      alert(friendly);
    } finally {
      if (zone) zone.classList.remove('le-upload-zone--loading');
    }
  }

  function wireZone(side) {
    const input = $('file' + side);
    const zone = $('zone' + side);
    if (!input || !zone) return;

    input.addEventListener('change', () => {
      const f = input.files && input.files[0];
      if (f) handleUpload(side, f);
    });

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('le-upload-zone--hover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('le-upload-zone--hover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('le-upload-zone--hover');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) handleUpload(side, f);
    });
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
  }

  async function consumePendingFromHome() {
    const raw = sessionStorage.getItem('lePending');
    if (!raw) return;
    sessionStorage.removeItem('lePending');
    try {
      const pending = JSON.parse(raw);
      if (Date.now() - pending.ts > 10 * 60 * 1000) return;
      if (pending.mode === MODE.VS_OURS) switchMode(MODE.VS_OURS, false);
      const res = await fetch(pending.dataUrl);
      const file = new File([await res.blob()], pending.name, { type: pending.type });
      await handleUpload(pending.side || 'A', file);
    } catch (err) {
      console.warn('Pending LE upload failed', err);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const initialMode = getModeFromUrl();
    setModeUI(initialMode);
    if (!initialMode) showWorkflow(false);

    $('pickVsOurs')?.addEventListener('click', () => switchMode(MODE.VS_OURS, true));
    $('pickCompareTwo')?.addEventListener('click', () => switchMode(MODE.COMPARE_TWO, true));
    document.body.addEventListener('click', (e) => {
      const sw = e.target.closest('[data-switch]');
      if (!sw) return;
      const m = sw.dataset.switch === MODE.VS_OURS ? MODE.VS_OURS : MODE.COMPARE_TWO;
      switchMode(m, false);
    });

    wireZone('A');
    wireZone('B');
    consumePendingFromHome();
    $('compareBtn')?.addEventListener('click', runCompare);
    $('leReviewSubmitBtn')?.addEventListener('click', submitForReview);
    document.querySelectorAll('.js-le-reset').forEach((btn) => btn.addEventListener('click', () => {
      ['formA', 'formB'].forEach((id) => $(id)?.reset());
      ['A', 'B'].forEach((s) => {
        const l = $('zone' + s + '_label');
        if (l) l.textContent = 'Drop PDF or image, or click to browse';
        const st = $(s.toLowerCase() + '_status');
        if (st) st.textContent = '';
        const n = $(s.toLowerCase() + '_notes');
        if (n) n.textContent = '';
      });
      lastUploadMeta = { fileName: '', lenderName: '' };
      showWorkflow(!!currentMode);
      $('leReviewSuccess').hidden = true;
      $('le-compare-results').hidden = true;
      $('leReviewMsg').textContent = '';
      if ($('leReviewPanel')) $('leReviewPanel').hidden = true;
      setModeUI(currentMode);
    }));
  });
})();
