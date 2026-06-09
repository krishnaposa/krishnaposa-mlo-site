/* Loan Estimate upload → OCR → compare */
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

  const LABELS = {
    [MODE.VS_OURS]: { a: 'Your current quote', b: 'Our quote (Innovative Mortgage)' },
    [MODE.COMPARE_TWO]: { a: 'Lender A', b: 'Lender B' }
  };

  function getModeFromUrl() {
    const p = new URLSearchParams(window.location.search).get('mode');
    return p === MODE.VS_OURS ? MODE.VS_OURS : MODE.COMPARE_TWO;
  }

  function termLabel(years) {
    const y = Math.round(Number(years) || 30);
    return y <= 15 ? '15 Year Fixed' : '30 Year Fixed';
  }

  /** Build competitive side-B from their extracted LE */
  function buildOurQuote(their) {
    const rates = window.RefiEval && window.RefiEval.estimateRate
      ? window.RefiEval.estimateRate({ term: termLabel(their.term), fico: '740-759', purpose: 'Purchase', ltv: 80 })
      : { base: 6.375 };

    const theirRate = Number(their.rate) || 0;
    let ourRate = rates.base;
    if (theirRate > 0) {
      ourRate = Math.min(theirRate - 0.125, rates.base);
      ourRate = Math.max(ourRate, 3.5);
    }

    const theirFees = Number(their.lender_fees) || 0;
    const ourFees = theirFees > 0
      ? Math.max(795, Math.round(theirFees * 0.82))
      : 995;

    const theirPoints = Number(their.points) || 0;
    const theirCredits = Number(their.credits) || 0;

    return {
      lender_name: 'Innovative Mortgage Services',
      amount: their.amount,
      rate: Math.round(ourRate * 1000) / 1000,
      term: their.term || 30,
      points: Math.max(0, theirPoints - 0.25),
      lender_fees: ourFees,
      credits: theirCredits + (theirFees > theirCredits + 900 ? 250 : 0),
      shop_total: their.shop_total,
      other_3p: their.other_3p,
      prepaids: their.prepaids,
      taxes_ins: their.taxes_ins,
      pmi: their.pmi,
      down: their.down,
      confidence: 'medium',
      notes: 'Estimated competitive quote from wholesale pricing. Schedule a call for a firm Loan Estimate.'
    };
  }

  function applyOurQuote(theirFields) {
    const ours = buildOurQuote(theirFields);
    fillForm('b', ours);
    const zoneB = $('zoneB');
    if (zoneB && currentMode === MODE.VS_OURS) {
      const lbl = $('zoneB_label');
      if (lbl) lbl.textContent = 'Competitive quote generated ✓';
    }
  }

  function setModeUI(mode) {
    currentMode = mode;
    const labels = LABELS[mode];
    const isVsOurs = mode === MODE.VS_OURS;

    document.body.dataset.leMode = mode;

    const banner = $('leModeBanner');
    if (banner) {
      banner.hidden = false;
      if (isVsOurs) {
        banner.innerHTML =
          '<strong>Second-opinion mode:</strong> Your uploaded Loan Estimate is compared against an estimated competitive quote from Innovative Mortgage. ' +
          '<a href="le-upload.html?mode=compare-two">Have two LEs from different lenders? Use compare mode →</a>';
      } else {
        banner.innerHTML =
          '<strong>Compare mode:</strong> Upload two Loan Estimates to compare lender vs lender. ' +
          '<a href="le-upload.html?mode=vs-ours">Only have one quote? Compare against ours →</a>';
      }
    }

    const heroLead = $('leHeroLead');
    if (heroLead) {
      heroLead.textContent = isVsOurs
        ? 'Upload the Loan Estimate you already have. We read the numbers and show how an estimated Innovative Mortgage quote stacks up on payment, cash to close, and 5-year cost. Educational only — not a loan offer.'
        : 'Upload two Loan Estimate PDFs or photos. We read the key numbers, let you fix anything that looks off, then show monthly payment, cash to close, and 5-year cost side by side.';
    }

    const titleA = $('titleA');
    const titleB = $('titleB');
    if (titleA) titleA.textContent = isVsOurs ? 'Your current quote' : 'Lender A — extracted fields';
    if (titleB) titleB.textContent = isVsOurs ? 'Our competitive quote' : 'Lender B — extracted fields';

    const zoneA = $('zoneA');
    const zoneB = $('zoneB');
    if (zoneA) {
      zoneA.querySelector('strong').textContent = isVsOurs ? 'Your Loan Estimate' : 'Lender A';
    }
    if (zoneB) {
      zoneB.hidden = false;
      zoneB.classList.toggle('le-upload-zone--ours', isVsOurs);
      const strong = zoneB.querySelector('strong');
      if (strong) strong.textContent = isVsOurs ? 'Our quote (auto-filled)' : 'Lender B';
      const lbl = $('zoneB_label');
      if (lbl && !lbl.textContent.includes('✓')) {
        lbl.textContent = isVsOurs
          ? 'Generated after you upload your LE'
          : 'Drop PDF or image, or click to browse';
      }
      if (isVsOurs) {
        zoneB.setAttribute('aria-disabled', 'true');
        zoneB.style.pointerEvents = 'none';
      } else {
        zoneB.removeAttribute('aria-disabled');
        zoneB.style.pointerEvents = '';
      }
    }

    const inputB = $('fileB');
    if (inputB) inputB.disabled = isVsOurs;

    document.querySelectorAll('[data-label-a]').forEach((el) => { el.textContent = labels.a; });
    document.querySelectorAll('[data-label-b]').forEach((el) => { el.textContent = labels.b; });

    const step1 = $('step1Text');
    if (step1) {
      step1.textContent = isVsOurs
        ? 'Your LE (we build our quote)'
        : 'PDF or photo for each lender';
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

  async function pdfFirstPageImage(file) {
    const pdfjsLib = initPdfJs();
    if (!pdfjsLib) return '';
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 2 });
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
    return canvas.toDataURL('image/jpeg', 0.9).split(',')[1] || '';
  }

  async function readFileContent(file) {
    let text = '';
    let imageBase64 = '';
    let mimeType = file.type || 'application/octet-stream';

    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
      text = await extractPdfText(file);
      if (text.trim().length < 200) {
        imageBase64 = await pdfFirstPageImage(file);
        mimeType = 'image/jpeg';
      }
    } else if (file.type.startsWith('image/')) {
      imageBase64 = await fileToBase64(file);
    } else {
      throw new Error('Upload a PDF or image (JPG, PNG)');
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
    if (!res.ok) throw new Error(data.error || 'OCR request failed');
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
      if (currentMode === MODE.VS_OURS) {
        const saveMo = res.monthly.a - res.monthly.b;
        const saveCash = res.cash.a - res.cash.b;
        const save5 = res.fiveYear.a - res.fiveYear.b;
        summary.innerHTML =
          (saveMo > 0
            ? `<p><strong>Monthly payment:</strong> Our quote is about <strong>${fmt(saveMo)}</strong> lower per month than your current offer.</p>`
            : saveMo < 0
              ? `<p><strong>Monthly payment:</strong> Your current offer is lower on payment — let's review fees and 5-year cost.</p>`
              : `<p><strong>Monthly payment:</strong> Similar between your quote and our estimate.</p>`) +
          (saveCash > 0
            ? `<p><strong>Cash to close:</strong> Our estimate needs about <strong>${fmt(saveCash)}</strong> less cash to close.</p>`
            : '') +
          (save5 > 0
            ? `<p><strong>5-year cost:</strong> Roughly <strong>${fmt(save5)}</strong> less over 5 years with our structure.</p>`
            : '') +
          '<p class="tiny muted">This is an educational estimate. Book a call for a firm Loan Estimate tailored to your file.</p>';
      } else {
        const cheaperMo = res.monthly.diff < 0 ? labels.b : res.monthly.diff > 0 ? labels.a : 'tie';
        const cheaperCash = res.cash.diff < 0 ? labels.b : res.cash.diff > 0 ? labels.a : 'tie';
        summary.innerHTML =
          `<p><strong>Monthly payment:</strong> ${cheaperMo === 'tie' ? 'Both are similar' : cheaperMo + ' is lower'} (${fmt(Math.abs(res.monthly.diff))}/mo difference).</p>` +
          `<p><strong>Cash to close:</strong> ${cheaperCash === 'tie' ? 'Both are similar' : cheaperCash + ' needs less cash'} (${fmt(Math.abs(res.cash.diff))} difference).</p>` +
          `<p><strong>5-year cost:</strong> ${fmt(Math.abs(res.fiveYear.diff))} ${res.fiveYear.diff < 0 ? 'less for ' + labels.b : res.fiveYear.diff > 0 ? 'less for ' + labels.a : 'same'} over 5 years.</p>`;
      }
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

  async function handleUpload(side, file, opts) {
    opts = opts || {};
    const zone = $('zone' + side);
    const label = $('zone' + side + '_label');
    if (zone) zone.classList.add('le-upload-zone--loading');
    if (label) label.textContent = 'Reading ' + file.name + '…';

    try {
      const { fields } = await ocrLoanEstimate(file);
      fillForm(side.toLowerCase(), fields);
      if (label) label.textContent = file.name + ' ✓';

      if (currentMode === MODE.VS_OURS && side === 'A') {
        applyOurQuote(fields);
        if (opts.autoCompare) runCompare();
      }
    } catch (err) {
      if (label) label.textContent = 'Upload failed — try again';
      alert(err.message || 'Could not read Loan Estimate');
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
    zone.addEventListener('click', () => {
      if (currentMode === MODE.VS_OURS && side === 'B') return;
      input.click();
    });
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (currentMode === MODE.VS_OURS && side === 'B') return;
        input.click();
      }
    });
  }

  async function consumePendingFromHome() {
    const raw = sessionStorage.getItem('lePending');
    if (!raw) return;
    sessionStorage.removeItem('lePending');
    try {
      const pending = JSON.parse(raw);
      if (Date.now() - pending.ts > 10 * 60 * 1000) return;
      if (pending.mode === MODE.VS_OURS) setModeUI(MODE.VS_OURS);
      const res = await fetch(pending.dataUrl);
      const file = new File([await res.blob()], pending.name, { type: pending.type });
      await handleUpload(pending.side || 'A', file, { autoCompare: pending.mode === MODE.VS_OURS });
    } catch (err) {
      console.warn('Pending LE upload failed', err);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setModeUI(getModeFromUrl());
    wireZone('A');
    wireZone('B');
    consumePendingFromHome();
    $('compareBtn')?.addEventListener('click', runCompare);
    $('resetBtn')?.addEventListener('click', () => {
      ['formA', 'formB'].forEach((id) => $(id)?.reset());
      ['A', 'B'].forEach((s) => {
        const l = $('zone' + s + '_label');
        if (l) {
          l.textContent = currentMode === MODE.VS_OURS && s === 'B'
            ? 'Generated after you upload your LE'
            : 'Drop PDF or image, or click to browse';
        }
        const st = $(s.toLowerCase() + '_status');
        if (st) st.textContent = '';
        const n = $(s.toLowerCase() + '_notes');
        if (n) n.textContent = '';
      });
      $('le-compare-results').hidden = true;
      setModeUI(currentMode);
    });
  });
})();
