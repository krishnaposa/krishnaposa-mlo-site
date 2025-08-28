// assets/js/header.js
(async function loadHeader() {
  const ensureMount = () => {
    let el = document.getElementById("header");
    if (!el) {
      el = document.createElement("div");
      el.id = "header";
      document.body.insertAdjacentElement("afterbegin", el);
    }
    return el;
  };

  const mountEl = ensureMount();

  const candidates = [
    "partials/header.html",   // root/partials
    "/partials/header.html",  // absolute
    "./partials/header.html"  // relative
  ];

  let html = null;
  for (const url of candidates) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status} on ${url}`);
      html = await res.text();
      console.info("[header] loaded:", url);
      break;
    } catch (err) {
      console.warn("[header] failed:", err.message);
    }
  }

  if (!html) {
    // visible fallback so you aren’t headerless
    mountEl.innerHTML = `
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
      </header>
    `;
    console.error("[header] could not load partials/header.html — rendered fallback header");
    wireMenu(); // wire up fallback
    return;
  }

  // Inject the real partial and wire it
  mountEl.innerHTML = html;
  wireMenu();

  function wireMenu() {
    const menu = document.getElementById("primary-menu");
    const toggle = document.querySelector(".menu-toggle");

    // Backdrop for mobile overlay
    let backdrop = document.getElementById("menu-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "menu-backdrop";
      backdrop.setAttribute("hidden", "");
      document.body.appendChild(backdrop);
    }

    // Active nav item
    if (menu) {
      const path = location.pathname.split("/").pop() || "index.html";
      menu.querySelectorAll("a[href]").forEach(a => {
        const href = a.getAttribute("href");
        if (href === path || (path === "index.html" && href === "index.html")) {
          a.setAttribute("aria-current", "page");
        }
        a.addEventListener("click", () => closeMenu(menu, toggle, backdrop));
      });
    }

    // Toggle
    if (toggle && menu) {
      toggle.addEventListener("click", (e) => {
        e.preventDefault();
        const isHidden = menu.hasAttribute("hidden");
        if (isHidden) openMenu(menu, toggle, backdrop);
        else closeMenu(menu, toggle, backdrop);
      });
      backdrop.addEventListener("click", () => closeMenu(menu, toggle, backdrop));
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") closeMenu(menu, toggle, backdrop));
      });
    }

    function openMenu(menu, toggle, backdrop) {
      menu.removeAttribute("hidden");
      toggle.setAttribute("aria-expanded", "true");
      backdrop.removeAttribute("hidden");
      document.body.classList.add("nav-open");
    }
    function closeMenu(menu, toggle, backdrop) {
      if (!menu.hasAttribute("hidden")) menu.setAttribute("hidden", "");
      toggle.setAttribute("aria-expanded", "false");
      if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
      document.body.classList.remove("nav-open");
    }
  }
})();