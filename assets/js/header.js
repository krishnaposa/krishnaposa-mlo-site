// assets/js/header.js — stable desktop/mobile behavior
(async function () {
  // inject partial
  const mountId = "header";
  let mount = document.getElementById(mountId);
  if (!mount) { mount = document.createElement("div"); mount.id = mountId; document.body.insertAdjacentElement("afterbegin", mount); }

  const paths = ["partials/header.html", "/partials/header.html", "./partials/header.html"];
  let html = null;
  for (const p of paths) {
    try {
      const res = await fetch(p, { credentials: "same-origin", cache: "no-store" });
      if (res.ok) { html = await res.text(); break; }
    } catch (_) {}
  }
  if (!html) return; // bail quietly if partial isn't found
  mount.innerHTML = html;

  // wire up
  const menu   = document.getElementById("primary-menu");
  const toggle = document.querySelector(".menu-toggle");
  if (!menu || !toggle) return;

  // backdrop
  let backdrop = document.getElementById("menu-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "menu-backdrop";
    backdrop.setAttribute("hidden", "");
    document.body.appendChild(backdrop);
  }

  // active link
  const path = location.pathname.split("/").pop() || "index.html";
  menu.querySelectorAll("a[href]").forEach(a => {
    const href = a.getAttribute("href");
    if (href === path || (path === "index.html" && href === "index.html")) a.setAttribute("aria-current", "page");
    a.addEventListener("click", () => setTimeout(closeMenu, 120)); // let nav fire first
  });

  // viewport sync that DOESN'T fight manual open state
  const mq = window.matchMedia("(min-width: 1024px)");
  function syncForViewport() {
    if (mq.matches) {
      // Desktop: menu visible, no overlay
      menu.removeAttribute("hidden");
      document.body.classList.remove("nav-open");
      if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
      toggle.setAttribute("aria-expanded", "false");
    } else {
      // Mobile: keep closed unless user has it open
      if (!document.body.classList.contains("nav-open")) {
        menu.setAttribute("hidden", "");
        toggle.setAttribute("aria-expanded", "false");
      }
    }
  }
  syncForViewport();
  (mq.addEventListener ? mq.addEventListener("change", syncForViewport)
                       : mq.addListener(syncForViewport)); // Safari

  // toggle handlers
  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    const isHidden = menu.hasAttribute("hidden");
    if (isHidden) openMenu(); else closeMenu();
  });
  backdrop.addEventListener("click", closeMenu);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeMenu(); });

  function openMenu() {
    // Only open as slide-in on mobile widths
    if (!mq.matches) {
      menu.removeAttribute("hidden");
      backdrop.removeAttribute("hidden");
      document.body.classList.add("nav-open");
      toggle.setAttribute("aria-expanded", "true");
    }
  }
  function closeMenu() {
    if (!mq.matches) {
      if (!menu.hasAttribute("hidden")) menu.setAttribute("hidden", "");
      if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  }
})();