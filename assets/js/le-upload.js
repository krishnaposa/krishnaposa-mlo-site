/* Loan Estimate upload → OCR → compare */
(function () {
  const $ = (id) => document.getElementById(id);
  const API = () => (window.LoanApi && window.LoanApi.base) || '';

  const FIELD_IDS = [
    'amount', 'rate', 'term', 'points', 'lender_fees', 'credits',
    'shop_total', 'other_3p', 'prepaids', 'taxes_ins', 'pmi', 'down'
  ];

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        const base64 = String(dataUrl).split(',')[1] || '';
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function initPdfJs() {
    if (!window.pdfjsLib) return null;
    const pdfjsLib = window.pdfjsLib;
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    return pdfjsLib;
  }

  async function extractPdfText(file) {
    const pdfjsLib = initPdfJs();
    if (!pdfjsLib) return '';
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    let text = '';
    const maxPages = Math.min(pdf.numPages, 3);
    for (let p = 1; p <= maxPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      text += content.items.map((it) => it.str).join(' ') + '\n';
    }
    return text;
  }

  async function pdfFirstPageImage(file) {
    const pdfjsLib = initPdfJs();
    if (!pdfjsLib) return '';
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
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
      } else {
        mimeType = 'application/pdf';
      }
    } else if (file.type.startsWith('image/')) {
      imageBase64 = await fileToBase64(file);
    } else {
      throw new Error('Upload a PDF or image (JPG, PNG)');
    }
    return { text, imageBase64, mimeType };
  }

  async function ocrLoanEstimate(file) {
    const { text, imageBase64, mimeType } = await readFileContent(file);
    const base = API();
    if (!base) throw new Error('Loan API not configured');

    const res = await fetch(base + '/leOcr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, imageBase64, mimeType })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'OCR request failed');
    return data;
  }

  function fillForm(prefix, fields) {
    FIELD_IDS.forEach((key) => {
      const el = $(prefix + '_' + key);
      if (!el || fields[key] === undefined) return;
      const v = fields[key];
      el.value = key === 'rate' ? v : v;
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
    if (notes && fields.notes) notes.textContent = fields.notes;
  }

  function renderResults(res) {
    const fmt = window.LECompare.fmtMoney;
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
      const cheaperMo = res.monthly.diff < 0 ? 'B' : res.monthly.diff > 0 ? 'A' : 'tie';
      const cheaperCash = res.cash.diff < 0 ? 'B' : res.cash.diff > 0 ? 'A' : 'tie';
      summary.innerHTML =
        `<p><strong>Monthly payment:</strong> Lender ${cheaperMo === 'tie' ? 'A and B are similar' : cheaperMo + ' is lower'} (${fmt(Math.abs(res.monthly.diff))}/mo difference).</p>` +
        `<p><strong>Cash to close:</strong> Lender ${cheaperCash === 'tie' ? 'A and B are similar' : cheaperCash + ' needs less cash'} (${fmt(Math.abs(res.cash.diff))} difference).</p>` +
        `<p><strong>5-year cost:</strong> ${fmt(res.fiveYear.diff)} ${res.fiveYear.diff < 0 ? 'less for B' : res.fiveYear.diff > 0 ? 'less for A' : 'same'} over 5 years.</p>`;
    }
    $('le-compare-results').hidden = false;
    $('le-compare-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function runCompare() {
    const A = window.LECompare.computeSide('a');
    const B = window.LECompare.computeSide('b');
    renderResults(window.LECompare.compareSides(A, B));
  }

  async function handleUpload(side, file) {
    const zone = $('zone' + side);
    const label = $('zone' + side + '_label');
    if (zone) zone.classList.add('le-upload-zone--loading');
    if (label) label.textContent = 'Reading ' + file.name + '…';

    try {
      const { fields } = await ocrLoanEstimate(file);
      fillForm(side.toLowerCase(), fields);
      if (label) label.textContent = file.name + ' ✓';
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
      const res = await fetch(pending.dataUrl);
      const blob = await res.blob();
      const file = new File([blob], pending.name, { type: pending.type });
      await handleUpload(pending.side || 'A', file);
    } catch (err) {
      console.warn('Pending LE upload failed', err);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    wireZone('A');
    wireZone('B');
    consumePendingFromHome();
    $('compareBtn')?.addEventListener('click', runCompare);
    $('resetBtn')?.addEventListener('click', () => {
      ['formA', 'formB'].forEach((id) => $(id)?.reset());
      ['A', 'B'].forEach((s) => {
        const l = $('zone' + s + '_label');
        if (l) l.textContent = 'Drop PDF or image, or click to browse';
        $(s.toLowerCase() + '_status') && ($(s.toLowerCase() + '_status').textContent = '');
      });
      $('le-compare-results').hidden = true;
    });
  });
})();
