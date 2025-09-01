/* assets/js/buyer-funnel.js
   Quick-qualify math, booking links, Realtor list w/ default logo, and Google Form opener
*/
(function () {
  // ---- CONFIG ----
  const APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxVkjSelQjFJbQc5zNAD9m8soIyPqrZ9ICCq06TmK8lT5evRB0wmLV4mkJ6sSmpbpfG/exec";
  const DEFAULT_AGENT_LOGO = "assets/img/realtor.png"; // used when none/invalid
  const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6";
  const GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfKpOQUQNw5-t98jd8uH524-n5M47ICyid_5vBUCRfWdpJRTA/viewform?hl=en";

  // Mortgage helpers (from mortgage-calc.js)
  const { cfg, parseNumber: num, fmtCurrency: fmt, calc } = window.MortgageCalc || {};
  const $ = (sel) => document.querySelector(sel);

  /* ---------------------- Booking links ---------------------- */
  ["#bookTop", "#bookBottom", "#bookSticky"].forEach((q) => {
    const el = $(q);
    if (el) el.href = BOOKING_URL;
  });

  /* ---------------------- Google Form opener ---------------------- */
  const formBtn = $("#openGoogleForm");
  if (formBtn) {
    const base = new URL(GOOGLE_FORM_URL, location.href);
    const params = new URLSearchParams(location.search);
    ["utm_source","utm_medium","utm_campaign","utm_term","utm_content"].forEach(k => {
      const v = params.get(k);
      if (v) base.searchParams.set(k, v);
    });
    if (!base.searchParams.has("hl")) base.searchParams.set("hl", "en");
    formBtn.addEventListener("click", () => {
      formBtn.href = base.toString();
      window.dataLayer && window.dataLayer.push({ event: "open_google_form" });
    }, { passive: true });
  }

  /* ---------------------- Realtor list (add + render) ---------------------- */
  const AGENTS_KEY = "agents_v1"; // array of {name, firm, email, logo}

  function getAgents() {
    try { return JSON.parse(localStorage.getItem(AGENTS_KEY) || "[]"); }
    catch { return []; }
  }
  function setAgents(list) {
    localStorage.setItem(AGENTS_KEY, JSON.stringify(list || []));
  }

  // Render list under the existing preview card. Creates a container if missing.
  function renderAgents() {
    const card = $("#agentCard");
    if (!card) return;

    let listWrap = $("#agentList");
    if (!listWrap) {
      listWrap = document.createElement("div");
      listWrap.id = "agentList";
      listWrap.style.marginTop = "1rem";
      listWrap.style.display = "grid";
      listWrap.style.gridTemplateColumns = "repeat(auto-fill,minmax(240px,1fr))";
      listWrap.style.gap = "12px";
      card.appendChild(listWrap);
    }
    listWrap.innerHTML = "";

    const agents = getAgents();

    // Also reflect the “first” agent into the simple header preview at the top
    const headName = $("#agentName");
    const headFirm = $("#agentFirm");
    const headAvatar = $("#agentAvatar");
    const first = agents[0];
    if (headName) headName.textContent = first ? (first.name || "—") : "No agent added";
    if (headFirm) headFirm.textContent = first ? (first.firm || "—") : "You can add one above";
    if (headAvatar) {
      headAvatar.style.width = "64px";
      headAvatar.style.height = "64px";
      headAvatar.style.objectFit = "cover";
      headAvatar.style.borderRadius = "50%";
      const src = first?.logo?.trim() || DEFAULT_AGENT_LOGO;
      headAvatar.onerror = () => { headAvatar.src = DEFAULT_AGENT_LOGO; };
      headAvatar.src = src;
      headAvatar.style.display = "block";
    }

    // Build each agent card
    agents.forEach((a, idx) => {
      const item = document.createElement("div");
      item.className = "card";
      item.style.display = "flex";
      item.style.gap = "10px";
      item.style.alignItems = "center";
      item.style.padding = "10px";

      const img = document.createElement("img");
      img.width = 48; img.height = 48;
      img.style.borderRadius = "50%";
      img.style.objectFit = "cover";
      img.alt = "Agent";
      img.src = (a.logo || "").trim() || DEFAULT_AGENT_LOGO;
      img.onerror = () => { img.src = DEFAULT_AGENT_LOGO; };

      const info = document.createElement("div");
      const nm = document.createElement("div");
      nm.style.fontWeight = "700";
      nm.textContent = a.name || "—";
      const fm = document.createElement("div");
      fm.className = "small";
      fm.textContent = a.firm || "—";
      const em = document.createElement("div");
      em.className = "tiny";
      em.textContent = a.email || "";
      info.appendChild(nm); info.appendChild(fm); info.appendChild(em);

      item.appendChild(img);
      item.appendChild(info);
      listWrap.appendChild(item);
    });
  }

  // Add/Update agent on Save (dedupe by email, append otherwise)
  document.addEventListener("click", (evt) => {
    const btn = evt.target.closest("#saveAgent");
    if (!btn) return;
    evt.preventDefault();

    const name  = ($("#agent_name")?.value || "").trim();
    const firm  = ($("#agent_firm")?.value || "").trim();
    const email = ($("#agent_email")?.value || "").trim();
    const logo  = ($("#agent_logo")?.value || "").trim();

    if (!name && !email && !firm && !logo) return;

    const agents = getAgents();
    const key = email.toLowerCase();
    const i = agents.findIndex(a => (a.email || "").toLowerCase() === key);

    if (i >= 0) {
      // Update existing by email
      agents[i] = { ...agents[i], name, firm, email, logo };
    } else {
      // Append new
      agents.push({ name, firm, email, logo });
    }

    setAgents(agents);
    renderAgents();

    // Send to Apps Script (so you receive it)
    sendAgentToWebhook({ name, firm, email, logo });

    // Tiny confirmation
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saved ✓";
    setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 900);
  });

  // POST to Apps Script without CORS headaches (form POST)
  function sendAgentToWebhook(agent) {
    if (!APPS_SCRIPT_URL) return;
    const form = document.createElement("form");
    form.action = APPS_SCRIPT_URL;
    form.method = "POST";
    form.target = "_self";
    form.style.display = "none";

    const add = (k, v) => {
      const input = document.createElement("input");
      input.type = "hidden"; input.name = k; input.value = v ?? "";
      form.appendChild(input);
    };

    // Payload
    add("type", "realtor_add");
    add("name", agent.name || "");
    add("firm", agent.firm || "");
    add("email", agent.email || "");
    add("logo", agent.logo || "");
    // pass through UTMs if present
    const utm = new URLSearchParams(location.search);
    ["utm_source","utm_medium","utm_campaign","utm_term","utm_content"].forEach(k => {
      const v = utm.get(k); if (v) add(k, v);
    });

    document.body.appendChild(form);
    // Avoid name="submit" collision
    const s = form.submit; s.call(form);
    setTimeout(() => form.remove(), 600);
  }

  // First render of list + header preview
  renderAgents();

  /* ---------------------- Quick Qualify calculator ---------------------- */
  $("#estimateBtn")?.addEventListener("click", () => {
    if (!calc) return;
    const price = num($("#price")?.value);
    const downInput = ($("#down")?.value || "").trim();
    const down = downInput.endsWith("%") ? price * num(downInput) : num(downInput || 0);
    const rateField = ($("#rate")?.value || (cfg && cfg.defaultRatePct) || "7%");
    const ratePct = rateField.toString().trim().endsWith("%") ? num(rateField) * 100 : num(rateField);
    const zip = ($("#zip")?.value || "").trim();
    const program = $("#program")?.value || "conventional";
    const income = num($("#income")?.value);
    const debts = num($("#debts")?.value || 0);

    if (!price || !income) {
      const m = $("#formMsg");
      if (m) m.textContent = "Please complete price and income (and down payment if available).";
      return;
    }
    const m = $("#formMsg"); if (m) m.textContent = "";

    const res = calc.totalMonthly({ price, down, ratePct, program, zip });
    const dti = calc.dti(res.total, debts, income);

    $("#pAndI")        && ($("#pAndI").textContent = fmt(res.pAndI));
    $("#taxes")        && ($("#taxes").textContent = fmt(res.taxes + res.ins + res.pmi));
    $("#totalPay")     && ($("#totalPay").textContent = fmt(res.total));
    $("#estimatesWrap")&& ($("#estimatesWrap").style.display = "grid");

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

    // Stash derived values (handy later)
    localStorage.setItem("lastEstimate", JSON.stringify({
      price, down, rate: ratePct, program,
      monthly: Math.round(res.total),
      dti: (dti * 100).toFixed(1)
    }));

    window.dataLayer && window.dataLayer.push({ event: "estimate_calculated" });
  });

  $("#resetBtn")?.addEventListener("click", () => {
    $("#estimatesWrap") && ($("#estimatesWrap").style.display = "none");
    $("#dtiLine")      && ($("#dtiLine").style.display = "none");
    $("#pmiLine")      && ($("#pmiLine").style.display = "none");
    $("#formMsg")      && ($("#formMsg").textContent = "");
    localStorage.removeItem("lastEstimate");
  });

  // Optional prefill from saved estimate
  (function prefillFromSaved() {
    try {
      const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
      if (saved.price) {
        if ($("#price"))   $("#price").value   = saved.price;
        if (saved.down && $("#down")) $("#down").value = saved.down;
        if ($("#rate"))    $("#rate").value    = isFinite(saved.rate) ? saved.rate.toFixed?.(2) + "%" : "";
        if ($("#program")) $("#program").value = saved.program || "conventional";
      }
    } catch(_) {}
  })();
})();