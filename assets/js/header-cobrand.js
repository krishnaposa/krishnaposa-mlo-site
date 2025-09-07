// assets/js/header-cobrand.js
document.addEventListener("DOMContentLoaded", function () {
  // ensure strip not duplicated
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

  // optionally inject cobrand.css if not already in <head>
  const cssHref = "/assets/css/cobrand.css?v=1";
  if (![...document.querySelectorAll('link[rel="stylesheet"]')].some(l => (l.href || "").includes("cobrand.css"))) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cssHref;
    (document.head || document.documentElement).appendChild(link);
  }
});