document.addEventListener("DOMContentLoaded", function () {
  // --- 1) Load header include as you already do (adjust path if needed) ---
  const headerTarget = document.getElementById("header");
  if (headerTarget) {
    fetch("/assets/includes/header.html")
      .then(res => res.ok ? res.text() : Promise.reject(res.status))
      .then(html => { headerTarget.innerHTML = html; })
      .catch(() => { /* optional: console.warn("Header include failed"); */ });
  }

  // --- 2) Ensure cobrand.css is present (inject <link> if not already loaded) ---
  const cssHref = "/assets/css/cobrand.css?v=1";
  const hasCobrandCSS = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
    .some(l => (l.href || "").includes("/assets/css/cobrand.css"));
  if (!hasCobrandCSS) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cssHref;
    // Put it late in <head> so it wins against earlier styles
    (document.head || document.documentElement).appendChild(link);
  }

  // --- 3) Inject the co-brand strip once, at the very top of <body> ---
  if (!document.querySelector(".cobrand-strip")) {
    const stripHTML = `
      <div class="cobrand-strip" role="region" aria-label="Co-branded">
        <div class="inner">
          <img src="https://www.krishposa.com/assets/img/headshot.jpg" alt="Krish Posa">
          <span>Mortgage by <strong>Krish Posa</strong></span>
          <span>|</span>
          <img src="https://www.krishposa.com/assets/img/brokerages/gvr.JPG" alt="GVR Realty LLC logo">
          <span>In partnership with <strong>GVR Realty LLC</strong></span>
        </div>
      </div>`;
    document.body.insertAdjacentHTML("afterbegin", stripHTML);
  }
});