/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand list, open Google Form, and Azure submit
*/
(function () {
  // ---- Mortgage helpers exposed by mortgage-calc.js ----
  const calcAPI = (window.MortgageCalc || {});
  const cfg  = calcAPI.cfg;
  const num  = calcAPI.parseNumber;
  const fmt  = calcAPI.fmtCurrency;
  const calc = calcAPI.calc;

  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ---- Config ----
  const GOOGLE_FORM_URL =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/viewform?hl=en";

  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";

  // Azure Function endpoint (add code if needed)
  const AZURE_FUNCTION_URL =
    "https://realtors-func-app-gbdufbcvazeug7ew.eastus2-01.azurewebsites.net/api/realtorSubmit";
  const AZURE_FUNCTION_CODE = ""; // <-- paste your function key here if required

  // 🔧 Use ABSOLUTE path so it works from any URL depth
  const REALTOR_FALLBACK_LOGO = "/assets/img/realtor.png";

  // Build the URL we actually POST to (handles optional function key)
  function buildAzureUrl() {
    try {
      const u = new URL(AZURE_FUNCTION_URL);
      if (AZURE_FUNCTION_CODE) u.searchParams.set("code", AZURE_FUNCTION_CODE);
      return u.toString();
    } catch {
      // If URL constructor fails (very old browsers), fall back to string concat
      return AZURE_FUNCTION_CODE
        ? AZURE_FUNCTION_URL + (AZURE_FUNCTION_URL.includes("?") ? "&" : "?") + "code=" + encodeURIComponent(AZURE_FUNCTION_CODE)
        : AZURE_FUNCTION_URL;
    }
  }

  // ---- Utility: simple UUID (fallback if crypto not available) ----
  function uuid() {
    try {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    } catch {}
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  // ---- Booking links ----
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q);
    if (el) el.href = BOOKING_URL;
  });

  // ==========================================================
  // REALTOR CO-BRAND — store A LIST, not a single agent
  // ==========================================================
  const LS_KEY = "agents"; // array of {id,name,firm,email,logo,addedAt}
  function loadAgents() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch { return []; }
  }
  function saveAgents(list) {
    localStorage.setItem(LS_KEY, JSON.stringify(list || []));
  }
  function addAgent(agent) {
    const list = loadAgents();
    const item = {
      id: uuid(),
      name: (agent.name || "").trim(),
      firm: (agent.firm || "").trim(),
      email: (agent.email || "").trim(),
      logo: (agent.logo || "").trim(),
      addedAt: new Date().toISOString()
    };
    if (!item.logo) item.logo = REALTOR_FALLBACK_LOGO; // fallback logo if none provided
    list.unshift(item); // newest first
    saveAgents(list);
    return item;
  }

  // Create (or reuse) a container for rendering the list
  function ensureAgentListContainer() {
    let wrap = $("#agentList");
    if (!wrap) {
      const card = $("#agentCard");
      if (card) {
        wrap = document.createElement("div");
        wrap.id = "agentList";
        wrap.className = "grid-3";
        wrap.style.marginTop = "1rem";
        card.appendChild(wrap);
      }
    }
    return wrap;
  }

  // Render the agents list + keep the original single preview in sync
  function drawAgents() {
    const wrap = ensureAgentListContainer();
    if (!wrap) return;
    wrap.innerHTML = ""; // clear

    const agents = loadAgents();

    // Sync the “preview” card with most recent agent (if any)
    const latest = agents[0];
    const avatar = $("#agentAvatar");
    const nameEl = $("#agentName");
    const firmEl = $("#agentFirm");

    if (latest) {
      if (avatar) {
        avatar.src = latest.logo || REALTOR_FALLBACK_LOGO;
        avatar.width = 64;
        avatar.height = 64;
        avatar.style.objectFit = "cover";
        avatar.style.borderRadius = "50%";
        avatar.addEventListener("error", () => { avatar.src = REALTOR_FALLBACK_LOGO; }, { once: true });
      }
      if (nameEl) nameEl.textContent = latest.name || "No agent added";
      if (firmEl) firmEl.textContent = latest.firm || "You can add one above";
    } else {
      if (avatar) avatar.src = REALTOR_FALLBACK_LOGO;
      if (nameEl) nameEl.textContent = "No agent added";
      if (firmEl) firmEl.textContent = "You can add one above";
    }

    // Build list UI
    agents.forEach((a) => {
      const card = document.createElement("div");
      card.className = "card";
      card.style.display = "flex";
      card.style.gap = "12px";
      card.style.alignItems = "center";

      const img = document.createElement("img");
      img.alt = "Agent logo or headshot";
      img.width = 48;
      img.height = 48;
      img.style.borderRadius = "50%";
      img.style.objectFit = "cover";
      img.loading = "lazy";
      img.decoding = "async";
      img.src = a.logo || REALTOR_FALLBACK_LOGO;
      img.addEventListener("error", () => { img.src = REALTOR_FALLBACK_LOGO; }, { once: true });

      const meta = document.createElement("div");
      const name = document.createElement("div");
      name.style.fontWeight = "700";
      name.textContent = a.name || "(no name)";
      const firm = document.createElement("div");
      firm.className = "small";
      firm.textContent = a.firm || "";
      const email = document.createElement("div");
      email.className = "tiny";
      email.textContent = a.email || "";
      meta.appendChild(name);
      meta.appendChild(firm);
      meta.appendChild(email);

      card.appendChild(img);
      card.appendChild(meta);
      wrap.appendChild(card);
    });
  }

  // Send realtor to Azure Function
  async function sendRealtorToAzure(agent) {
    const url = buildAzureUrl();
    const payload = {
      ...agent,
      source: "buyer-funnel",
      page: location.href,
      ua: navigator.userAgent,
      site_ts: new Date().toISOString()
    };

    // Try fetch first; if that fails due to CORS, try sendBeacon to a mirror route if you add one
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`Azure HTTP ${res.status}: ${txt || res.statusText}`);
      }
      try { return await res.json(); } catch { return {}; }
    } catch (err) {
      // Optional beacon fallback (only if you expose an anonymous endpoint)
      // navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], { type: "application/json" }));
      throw err;
    }
  }

  // Save button handler — adds to list (not replace) + fallback logo + sends to Azure
  const saveBtn = $("#saveAgent");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const newAgent = {
        name:  $("#agent_name")?.value || "",
        firm:  $("#agent_firm")?.value || "",
        email: $("#agent_email")?.value || "",
        logo:  $("#agent_logo")?.value || ""
      };

      // Minimal validation: require at least name or email
      if (!(newAgent.name || newAgent.email)) {
        toast("Please enter at least a name or email.", "warn");
        return;
      }

      const saved = addAgent(newAgent);
      drawAgents();

      try {
        await sendRealtorToAzure(saved);
        toast("Realtor saved and sent ✅", "ok");
      } catch (err) {
        console.error(err);
        toast("Saved locally. Couldn’t reach server.", "error");
      }
    }, { once: false }); // allow multiple saves
  }

  function toast(text, type) {
    const el = document.createElement("div");
    el.textContent = text;
    el.style.position = "fixed";
    el.style.bottom = "16px";
    el.style.left = "50%";
    el.style.transform = "translateX(-50%)";
    el.style.background =
      type === "ok" ? "rgba(11,95,255,.95)" :
      type === "warn" ? "rgba(255,193,7,.95)" :
      "rgba(220,53,69,.95)";
    el.style.color = "#fff";
    el.style.padding = "10px 14px";
    el.style.borderRadius = "10px";
    el.style.fontSize = ".9rem";
    el.style.zIndex = "9999";
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2000);
  }

  // Initial draw
  drawAgents();


// Replace with your function URL + ?code=<function-key>
const INTAKE_URL = "https://realtors-func-app-XXXX.azurewebsites.net/api/intake/submit?code=YOUR_FUNCTION_KEY";

document.querySelector("#intakeForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.querySelector("#submitBtn");
  const msg = document.querySelector("#submitMsg");
  btn && (btn.disabled = true, btn.textContent = "Submitting…");
  msg && (msg.textContent = "");

  const payload = {
    fullName:   document.querySelector("#fullName")?.value?.trim(),
    email:      document.querySelector("#email")?.value?.trim(),
    phone:      document.querySelector("#phone")?.value?.trim(),
    timeline:   document.querySelector("#timeline")?.value,
    occupancy:  document.querySelector("#occupancy")?.value,
    source:     document.querySelector("#source")?.value,
    estPrice:   document.querySelector("#estPrice")?.value?.trim(),
    estDown:    document.querySelector("#estDown")?.value?.trim(),
    employment: document.querySelector("#employment")?.value,
    coBorrower: document.querySelector("#coBorrower")?.value,
    notes:      document.querySelector("#notes")?.value?.trim(),

  };

  try {
    const res = await fetch(INTAKE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      mode: "cors",
      cache: "no-store",
      credentials: "omit"
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.error || `HTTP ${res.status}`);
    msg && (msg.textContent = "✅ Thanks! I’ll follow up shortly.");
    e.currentTarget.reset();
  } catch (err) {
    console.error(err);
    msg && (msg.textContent = "Sorry—there was a problem sending your info. Please try again or call/text.");
  } finally {
    btn && (btn.disabled = false, btn.textContent = "Submit Pre-Approval");
  }
});
  // ==========================================================
  // ESTIMATE CALCULATOR (gracefully no-op if calc helpers missing)
  // ==========================================================
  $("#estimateBtn")?.addEventListener("click", () => {
    if (!calc || !num || !fmt) return;

    const price = num($("#price")?.value);
    const downInput = ($("#down")?.value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = ($("#rate")?.value || (cfg && cfg.defaultRatePct));
    const ratePct = (rateField?.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField));
    const zip = ($("#zip")?.value || "").trim();
    const program = $("#program")?.value || "conventional";
    const income = num($("#income")?.value);
    const debts = num($("#debts")?.value || 0);

    if (!price || !income) {
      $("#formMsg") && ($("#formMsg").textContent = "Please complete price and income (and down payment if available).");
      return;
    }
    $("#formMsg") && ($("#formMsg").textContent = "");

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI")         && ($("#pAndI").textContent    = fmt(res.pAndI));
    $("#taxes")         && ($("#taxes").textContent    = fmt(res.taxes + res.ins + res.pmi));
    $("#totalPay")      && ($("#totalPay").textContent = fmt(res.total));
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "grid");

    const dtiEl = $("#dtiLine");
    if (dtiEl) {
      dtiEl.style.display = "";
      dtiEl.innerHTML = `Estimated DTI: <strong>${(dti * 100).toFixed(1)}%</strong>. Many programs prefer under 43 percent.`;
    }

    const pmiLine = $("#pmiLine");
    if (pmiLine) {
      if (program === "conventional" && res.ltv > 0.80) {
        pmiLine.style.display = "";
        pmiLine.textContent = "Mortgage insurance estimated due to down payment under 20 percent. This can drop as LTV improves.";
      } else {
        pmiLine.style.display = "none";
      }
    }

    // Stash derived values in hidden fields in case you ever need them again
    $("#h_estMonthly") && ($("#h_estMonthly").value = Math.round(res.total));
    $("#h_estDTI")     && ($("#h_estDTI").value     = `${(dti * 100).toFixed(1)}%`);

    localStorage.setItem("lastEstimate",
      JSON.stringify({ price, down, rate: ratePct, program, monthly: Math.round(res.total), dti: (dti * 100).toFixed(1) })
    );

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")      && ($("#dtiLine").style.display = "none");
    $("#pmiLine")      && ($("#pmiLine").style.display = "none");
    $("#formMsg")      && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Prefill some fields from last estimate (nice-to-have)
  (function prefillFromSaved() {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price"))   $("#price").value   = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate"))    $("#rate").value    = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch {}
  })();

  // ==========================================================
  // INTAKE: open Google Form in a new tab (mobile-friendly)
  // ==========================================================
  (function wireOpenFormButton() {
    const openBtn = $("#openGoogleForm");
    if (!openBtn) return;
    // Ensure href is set (in case HTML didn’t include it)
    openBtn.href = GOOGLE_FORM_URL;
    openBtn.target = "_blank";
    openBtn.rel = "noopener";
    openBtn.addEventListener("click", () => {
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: "open_google_form" });
    }, { passive: true });
  })();

  // Ensure avatar fallback if initial HTML has a broken/missing src
  (function hardenAvatarFallback() {
    const avatar = $("#agentAvatar");
    if (!avatar) return;
    avatar.addEventListener("error", () => { avatar.src = REALTOR_FALLBACK_LOGO; }, { once: true });
    if (!avatar.getAttribute("src") || !avatar.getAttribute("src").trim()) {
      avatar.src = REALTOR_FALLBACK_LOGO;
    }
  })();
})();