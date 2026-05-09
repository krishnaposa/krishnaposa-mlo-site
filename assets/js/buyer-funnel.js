/* assets/js/buyer-funnel.js
   Estimate math, agent co-brand list, open Google Form, and Azure submit
*/
(function () {
  // ---- Mortgage helpers exposed by mortgage-calc.js ----
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc || {};
  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ---- Config ----
  const GOOGLE_FORM_URL =
    "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/viewform?hl=en";

  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";

  // Azure Function endpoint (add code if needed)
  const AZURE_FUNCTION_URL =
    "https://realtors-func-app-gbdufbcvazeug7ew.eastus2-01.azurewebsites.net/api/realtorSubmit";
  const AZURE_FUNCTION_CODE = ""; // <-- if you have a function key, paste it here

  const REALTOR_FALLBACK_LOGO = "assets/img/realtor.png"; // used if no/bad logo

  // Build the URL we actually POST to (handles optional function key)
  function buildAzureUrl() {
    if (!AZURE_FUNCTION_CODE) return AZURE_FUNCTION_URL;
    const u = new URL(AZURE_FUNCTION_URL);
    u.searchParams.set("code", AZURE_FUNCTION_CODE);
    return u.toString();
  }

  // ---- Utility: simple UUID (fallback if crypto not available) ----
  function uuid() {
    if (crypto && crypto.randomUUID) return crypto.randomUUID();
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
    // fallback logo if none provided
    if (!item.logo) item.logo = REALTOR_FALLBACK_LOGO;
    list.unshift(item); // add to top (newest first)
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

  // Render the agents list. Also keeps the original single preview in sync with the most recent.
  function drawAgents() {
    const wrap = ensureAgentListContainer();
    if (!wrap) return;
    wrap.innerHTML = ""; // clear

    const agents = loadAgents();

    // Keep original preview in sync with the latest agent (if any)
    const latest = agents[0];
    if (latest) {
      const avatar = $("#agentAvatar");
      const nameEl = $("#agentName");
      const firmEl = $("#agentFirm");
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
      // No agents yet: reset the preview
      const avatar = $("#agentAvatar");
      const nameEl = $("#agentName");
      const firmEl = $("#agentFirm");
      if (avatar) avatar.src = "";
      if (nameEl) nameEl.textContent = "No agent added";
      if (firmEl) firmEl.textContent = "You can add one above";
    }

    // Build the list UI
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

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // CORS: make sure your Function App has your domain in CORS allowed origins
      mode: "cors",
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`Azure error ${res.status}: ${txt || res.statusText}`);
    }
    // if your function returns JSON
    let data = {};
    try { data = await res.json(); } catch {}
    return data;
  }

  // Save button handler — adds to list (not replace) + fallback logo + sends to Azure
  $("#saveAgent")?.addEventListener("click", async () => {
    const newAgent = {
      name:  $("#agent_name")?.value || "",
      firm:  $("#agent_firm")?.value || "",
      email: $("#agent_email")?.value || "",
      logo:  $("#agent_logo")?.value || ""
    };

    const saved = addAgent(newAgent);
    drawAgents();

    // Try to send to Azure (non-blocking UX)
    try {
      await sendRealtorToAzure(saved);
      // Tiny toast
      const ok = document.createElement("div");
      ok.textContent = "Realtor saved and sent ✅";
      ok.style.position = "fixed";
      ok.style.bottom = "16px";
      ok.style.left = "50%";
      ok.style.transform = "translateX(-50%)";
      ok.style.background = "rgba(11,95,255,.95)";
      ok.style.color = "#fff";
      ok.style.padding = "10px 14px";
      ok.style.borderRadius = "10px";
      ok.style.fontSize = ".9rem";
      ok.style.zIndex = "9999";
      document.body.appendChild(ok);
      setTimeout(() => ok.remove(), 1800);
    } catch (err) {
      console.error(err);
      const warn = document.createElement("div");
      warn.textContent = "Saved locally. Couldn’t reach server.";
      warn.style.position = "fixed";
      warn.style.bottom = "16px";
      warn.style.left = "50%";
      warn.style.transform = "translateX(-50%)";
      warn.style.background = "rgba(220,53,69,.95)";
      warn.style.color = "#fff";
      warn.style.padding = "10px 14px";
      warn.style.borderRadius = "10px";
      warn.style.fontSize = ".9rem";
      warn.style.zIndex = "9999";
      document.body.appendChild(warn);
      setTimeout(() => warn.remove(), 2200);
    }
  });

  // Initial draw
  drawAgents();

  // ==========================================================
  // ESTIMATE CALCULATOR (unchanged behavior)
  // ==========================================================
  $("#estimateBtn")?.addEventListener("click", () => {
    if (!calc || !num || !fmt) return;

    const price = num($("#price")?.value);
    const downInput = ($("#down")?.value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = ($("#rate")?.value || cfg?.defaultRatePct);
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
    openBtn.addEventListener("click", () => {
      // Push a GTM event if present
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: "open_google_form" });
      // default behavior is just following the anchor target=_blank
    }, { passive: true });
  })();

  // Ensure avatar fallback if initial HTML has a broken/missing src
  (function hardenAvatarFallback() {
    const avatar = $("#agentAvatar");
    if (!avatar) return;
    avatar.addEventListener("error", () => { avatar.src = REALTOR_FALLBACK_LOGO; }, { once: true });
    if (!avatar.getAttribute("src")) avatar.src = REALTOR_FALLBACK_LOGO;
  })();
})();