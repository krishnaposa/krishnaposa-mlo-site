(function () {
  // ===== CONFIG =====
  // Use your real function URL (anonymous). Do not include a function key in public code.
  const API_URL = "https://realtors-func-app-gbdufbcvazegue7ew.eastus2-01.azurewebsites.net/api/realtorSubmit";

  const form = document.getElementById("realtor-form");
  if (!form) return;

  const loadedAt = document.getElementById("loadedAt");
  loadedAt.value = Date.now().toString();

  const alertBox = document.getElementById("realtor-alert");
  const submitBtn = document.getElementById("submitBtn");
  const formStatus = document.getElementById("formStatus");

  function setBusy(b) {
    submitBtn.disabled = b;
    formStatus.textContent = b ? "Submitting…" : "";
  }

  function showBanner(type, msg) {
    alertBox.innerHTML = `<div class="${type === "success" ? "success-banner" : "error-banner"}">${msg}</div>`;
    alertBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function setFieldError(name, msg) {
    const el = form.querySelector(`[data-error-for="${name}"]`);
    if (el) el.textContent = msg || "";
  }

  function validate() {
    let ok = true;
    setFieldError("name", "");
    setFieldError("email", "");

    const name = form.name.value.trim();
    const email = form.email.value.trim();

    if (!name) { setFieldError("name", "Please enter your full name."); ok = false; }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFieldError("email", "Please enter a valid email.");
      ok = false;
    }

    // Honeypot
    if (form.website && form.website.value) ok = false;

    // Simple time guard: at least 3 seconds after load
    const sinceLoad = Date.now() - Number(loadedAt.value || 0);
    if (sinceLoad < 3000) ok = false;

    return ok;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    alertBox.innerHTML = "";

    if (!validate()) {
      showBanner("error", "Please fix the highlighted fields and try again.");
      return;
    }

    setBusy(true);

    const payload = {
      name: form.name.value.trim(),
      email: form.email.value.trim(),
      phone: form.phone.value.trim(),
      firm: form.firm.value.trim(),
      logo: form.logo.value.trim(),
      notes: form.notes.value.trim()
    };

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        // No credentials; CORS handled in the Function
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        throw new Error(data.error || `Request failed (${res.status})`);
      }

      // Success UX
      form.reset();
      loadedAt.value = Date.now().toString();
      showBanner("success", "Thanks — your application was received. I’ll follow up within one business day.");
      formStatus.textContent = "";

      // GTM
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: "realtor_submit_success", email: payload.email, firm: payload.firm || "" });

    } catch (err) {
      console.error(err);
      showBanner("error", "Sorry, we couldn’t submit right now. Please try again in a minute.");
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: "realtor_submit_error" });
    } finally {
      setBusy(false);
    }
  });
})();