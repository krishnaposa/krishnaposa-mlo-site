// assets/js/header.js  — Baseline v2 (diagnostics on)
(async function () {
  const log = (...a) => console.log("[header]", ...a);
  const warn = (...a) => console.warn("[header]", ...a);
  const error = (...a) => console.error("[header]", ...a);

  // Ensure mount exists
  let mount = document.getElementById("header");
  if (!mount) {
    mount = document.createElement("div");
    mount.id = "header";
    document.body.insertAdjacentElement("afterbegin", mount);
    log("Created #header mount dynamically");
  }

  // Try common paths (root, absolute, relative)
  const paths = ["partials/header.html", "/partials/header.html", "./partials/header.html"];
  let html = null, used = null;

  for (const p of paths) {
    try {
      const res = await fetch(p, { credentials: "same-origin", cache: "no-store" });
      log("Fetch", p, "=>", res.status);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      html = await res.text();
      used = p;
      break;
    } catch (e) {
      warn("Failed", p, e.message);
    }
  }

  if (!html) {
    error("Could not load header partial. Rendering fallback header.");
    mount.innerHTML = `
      <header class="site-header">
        <div class="container topbar">
          <div class="brand">
            <a href="index.html" class="logo" aria-label="Home">KP</a>
            <div class="brand-text">
              <h1>Krish Posa</h1>
              <p>Mortgage Loan Officer · NMLS #2533287</p>
            </div>
          </div>
          <nav class="nav" id="site-nav">
            <button class="menu-toggle" aria-label="Toggle menu" aria-controls="primary-menu" aria-expanded="false">☰</button>
            <ul class="menu" id="primary-menu" hidden>
              <li><a href="index.html">Home</a></li>
              <li><a href="loans.html">Loan Programs</a></li>
              <li><a href="resources.html">Resources</a></li>
              <li><a href="loan-advisor.html">Loan Advisor <span class="tag-ai">AI</span></a></li>
              <li><a href="about.html">About</a></li>
              <li><a href="calculator-le-compare.html">Compare Loan Estimates</a></li>
              <li><a href="blog.html" class="btn-outline">Blog</a></li>
              <li><a class="btn" href="https://www.myperfectlending.com/" target="_blank" rel="noopener">Apply Now</a></li>
            </ul>
          </nav>
        </div>
      </header>`;
    wire();
    return;
  }

  mount.innerHTML = html;
  log("Loaded:", used);
  wire();

  function wire() {
    const menu   = document.getElementById("primary-menu");
    const toggle = document.querySelector(".menu-toggle");
    if (!menu || !toggle) { error("Missing #primary-menu or .menu-toggle"); return; }

    // Backdrop (for mobile overlay)
    let backdrop = document.getElementById("menu-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "menu-backdrop";
      backdrop.setAttribute("hidden", "");
      document.body.appendChild(backdrop);
    }

    // Active page state
    const path = location.pathname.split("/").pop() || "index.html";
    menu.querySelectorAll("a[href]").forEach(a => {
      const href = a.getAttribute("href");
      if (href === path || (path === "index.html" && href === "index.html")) {
        a.setAttribute("aria-current", "page");
      }
      // Let navigation occur, then close menu
      a.addEventListener("click", () => setTimeout(closeMenu, 120));
    });

    // Toggle handlers
    toggle.addEventListener("click", (e) => {
      e.preventDefault();
      menu.hasAttribute("hidden") ? openMenu() : closeMenu();
    });
    backdrop.addEventListener("click", closeMenu);
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeMenu(); });

    function openMenu() {
      menu.removeAttribute("hidden");
      backdrop.removeAttribute("hidden");
      document.body.classList.add("nav-open");
      toggle.setAttribute("aria-expanded", "true");
      log("Menu opened");
    }
    function closeMenu() {
      if (!menu.hasAttribute("hidden")) menu.setAttribute("hidden", "");
      if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
      log("Menu closed");
    }
  }
})();