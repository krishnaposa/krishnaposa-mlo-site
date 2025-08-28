// assets/js/header.js  — Baseline v1
(async function () {
  const mountId = "header";
  let mount = document.getElementById(mountId);
  if (!mount) {
    mount = document.createElement("div");
    mount.id = mountId;
    document.body.insertAdjacentElement("afterbegin", mount);
  }

  // Fetch the partial (try a few paths)
  const paths = ["partials/header.html", "/partials/header.html", "./partials/header.html"];
  let html = null, used = null;
  for (const p of paths) {
    try {
      const res = await fetch(p, { credentials: "same-origin" });
      if (res.ok) { html = await res.text(); used = p; break; }
      console.warn("[header] HTTP", res.status, "on", p);
    } catch (e) { console.warn("[header]", e.message, "on", p); }
  }

  if (!html) {
    console.error("[header] Failed to load header partial — check file path.");
    return;
  }
  mount.innerHTML = html;
  console.info("[header] Loaded:", used);

  // Wire up toggle
  const menu   = document.getElementById("primary-menu");
  const toggle = document.querySelector(".menu-toggle");
  if (!menu || !toggle) { console.error("[header] Missing menu or toggle"); return; }

  // Backdrop
  let backdrop = document.getElementById("menu-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "menu-backdrop";
    backdrop.setAttribute("hidden", "");
    document.body.appendChild(backdrop);
  }

  // Active link
  const path = location.pathname.split("/").pop() || "index.html";
  menu.querySelectorAll("a[href]").forEach(a => {
    const href = a.getAttribute("href");
    if (href === path || (path === "index.html" && href === "index.html")) {
      a.setAttribute("aria-current", "page");
    }
    // Let navigation happen, then close
    a.addEventListener("click", () => setTimeout(closeMenu, 100));
  });

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
  }
  function closeMenu() {
    if (!menu.hasAttribute("hidden")) menu.setAttribute("hidden", "");
    if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
    document.body.classList.remove("nav-open");
    toggle.setAttribute("aria-expanded", "false");
  }
})();