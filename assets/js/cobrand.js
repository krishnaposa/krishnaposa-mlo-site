document.addEventListener("DOMContentLoaded", function() {
  const strip = `
    <div class="cobrand-strip">
      <div class="inner">
        <img src="https://www.krishposa.com/assets/img/headshot.jpg" alt="Krish Posa">
        <span>Mortgage by <strong>Krish Posa</strong></span>
        <span>|</span>
        <img src="https://www.krishposa.com/assets/img/brokerages/gvr.JPG" alt="GVR Realty LLC logo">
        <span>In partnership with <strong>GVR Realty LLC</strong></span>
      </div>
    </div>`;
  document.body.insertAdjacentHTML("afterbegin", strip);
});