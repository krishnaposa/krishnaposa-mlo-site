/* Homepage secure drop zone → le-upload.html */
(function () {
  const MAX_BYTES = 6 * 1024 * 1024;
  const TARGET = 'le-upload.html';

  function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  async function stashAndGo(file, side) {
    if (file.size > MAX_BYTES) {
      alert('File is too large. Please use a file under 6 MB or upload directly on the compare page.');
      window.location.href = TARGET;
      return;
    }
    const dataUrl = await fileToDataUrl(file);
    sessionStorage.setItem('lePending', JSON.stringify({
      side: side || 'A',
      name: file.name,
      type: file.type || 'application/octet-stream',
      dataUrl,
      ts: Date.now()
    }));
    window.location.href = TARGET;
  }

  function wireZone(zoneId, inputId, side) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;

    input.addEventListener('change', () => {
      const f = input.files && input.files[0];
      if (f) stashAndGo(f, side);
    });

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('homev2-dropzone--hover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('homev2-dropzone--hover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('homev2-dropzone--hover');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) stashAndGo(f, side);
    });
    zone.addEventListener('click', (e) => {
      if (e.target === input) return;
      input.click();
    });
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.click();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    wireZone('homeDropzone', 'homeFile', 'A');
  });
})();
