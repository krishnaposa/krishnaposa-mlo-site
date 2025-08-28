// assets/js/header.js
fetch("partials/header.html")
  .then(res => res.text())
  .then(html => {
    const mount = document.getElementById("header");
    if (mount) mount.innerHTML = html;
    else document.body.insertAdjacentHTML("afterbegin", html);

    const menu = document.getElementById("primary-menu");
    const toggle = document.querySelector(".menu-toggle");

    // Backdrop
    let backdrop = document.getElementById("menu-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "menu-backdrop";
      backdrop.setAttribute("hidden", "");
      document.body.appendChild(backdrop);
    }

    // Active nav + close on link click
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
        if (ev.key === "Escape") closeMenu(menu, toggle, backdrop);
      });
    }
  })
  .catch(err => console.error("Error loading header:", err));

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