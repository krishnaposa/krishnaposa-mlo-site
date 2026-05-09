document.addEventListener("DOMContentLoaded", function () {
  // Avoid duplicates if the header includes it on some pages
  if (document.querySelector(".cobrand-strip")) return;

  const stripHTML = `
    <div class="cobrand-strip" role="region" aria-label="Co-branded">
      <div class="inner">
        <img src="https://www.krishposa.com/assets/img/headshot.jpg" alt="Krish Posa">
        <span>Mortgage by <strong>Krish Posa</strong></span>
        <span>|</span>
        <img src="https://www.krishposa.com/assets/img/realtors/raghavaProfile.JPG" alt="Serene Georgia Realty">
        <span>In partnership with <strong>Serene Georgia Realty</strong></span>
      </div>
    </div>`;

  // Insert right after <body> so it sits above your header include
  document.body.insertAdjacentHTML("afterbegin", stripHTML);
});