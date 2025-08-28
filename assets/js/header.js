// assets/js/header.js — simple & reliable dropdown
(async function () {
  // Inject the partial
  const mountId = "header";
  let mount = document.getElementById(mountId);
  if (!mount) {
    mount = document.createElement("div");
    mount.id = mountId;
    document.body.insertAdjacentElement("afterbegin", mount);
  }

  const paths = ["partials/header.html", "/partials/header.html", "./partials/header.html"];
  let html = null;
  for (const p of paths) {
    try {
      const res = await fetch(p, { credentials: "same-origin", cache: "no-store" });
      if (res.ok) { html = await res.text(); break; }
    } catch (_) {}
  }
  if (!html) return;

  mount.innerHTML = html;

  // Wire up
  const menu   = document.getElementById("primary-menu");
  const toggle = document.querySelector(".menu-toggle");
  if (!menu || !toggle) return;

  // Ensure no [hidden] is left on the menu (partial ships with hidden)
  if (menu.hasAttribute("hidden")) menu.removeAttribute("hidden");

  // Active link
  const path = location.pathname.split("/").pop() || "index.html";
  menu.querySelectorAll("a[href]").forEach(a => {
    const href = a.getAttribute("href");
    if (href === path || (path === "index.html" && href === "index.html")) {
      a.setAttribute("aria-current", "page");
    }
    // Close mobile dropdown *after* navigation triggers
    a.addEventListener("click", () => setTimeout(() => {
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }, 50));
  });

  // Toggle (mobile only)
  const mq = window.matchMedia("(min-width: 1024px)");
  function syncDesktop() {
    if (mq.matches) {
      // Desktop: visible inline, no dropdown state
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  }
  syncDesktop();
  (mq.addEventListener ? mq.addEventListener("change", syncDesktop) : mq.addListener(syncDesktop));

  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    if (mq.matches) return; // ignore on desktop
    const open = document.body.classList.toggle("nav-open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  // Close on ESC (mobile)
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });
})();