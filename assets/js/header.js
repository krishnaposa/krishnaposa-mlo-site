// assets/js/header.js — final simple dropdown (desktop inline)
(async function () {
  // --- inject the header partial ---
  const mountId = "header";
  let mount = document.getElementById(mountId);
  if (!mount) {
    mount = document.createElement("div");
    mount.id = mountId;
    document.body.insertAdjacentElement("afterbegin", mount);
  }

  const paths = ["partials/header.html", "https://www.krishposa.com/partials/header.html", "./partials/header.html"];
  let html = null;
  for (const p of paths) {
    try {
      const res = await fetch(p, { credentials: "same-origin", cache: "no-store" });
      if (res.ok) { html = await res.text(); break; }
    } catch (_) {}
  }
  if (!html) return;

  mount.innerHTML = html;

  // --- wire up behavior ---
  const menu   = document.getElementById("primary-menu");
  const toggle = document.querySelector(".menu-toggle");
  if (!menu || !toggle) return;

  // partial ships with [hidden]; remove once so CSS can control visibility
  if (menu.hasAttribute("hidden")) menu.removeAttribute("hidden");

  // active page state
  const path = location.pathname.split("/").pop() || "index.html";
  menu.querySelectorAll("a[href]").forEach(a => {
    const href = a.getAttribute("href");
    if (href === path || (path === "index.html" && href === "index.html")) {
      a.setAttribute("aria-current", "page");
    }
    // close mobile dropdown after navigation starts
    a.addEventListener("click", () => setTimeout(closeMobile, 100));
  });

  // viewport sync (desktop inline; mobile collapsible)
  const mq = window.matchMedia("(min-width: 1024px)");
  function syncForViewport() {
    if (mq.matches) {
      // desktop: always visible, no dropdown state
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    } else {
      // mobile: start closed unless user opened it already
      if (!document.body.classList.contains("nav-open")) {
        toggle.setAttribute("aria-expanded", "false");
      }
    }
  }
  syncForViewport();
  (mq.addEventListener ? mq.addEventListener("change", syncForViewport)
                       : mq.addListener(syncForViewport)); // Safari

  // toggle button
  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    if (mq.matches) return; // ignore on desktop
    const open = !document.body.classList.contains("nav-open");
    document.body.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });

  // close on ESC (mobile)
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
      closeMobile();
    }
  });

  function closeMobile() {
    if (!mq.matches) {
      document.body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  }
})();