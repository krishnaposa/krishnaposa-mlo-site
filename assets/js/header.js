// assets/js/header.js
fetch("partials/header.html")
  .then(res => res.text())
  .then(html => {
    // inject at the top of <body>
    const mount = document.getElementById("header");
    if (mount) mount.innerHTML = html;
    else document.body.insertAdjacentHTML("afterbegin", html);

    // re-query after injection
    const menu = document.getElementById("primary-menu");
    const toggle = document.querySelector(".menu-toggle");

    // add a backdrop for clicks outside the menu
    let backdrop = document.getElementById("menu-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "menu-backdrop";
      backdrop.setAttribute("hidden", "");
      document.body.appendChild(backdrop);
    }

    // set active nav item
    if (menu) {
      const path = location.pathname.split("/").pop() || "index.html";
      const links = menu.querySelectorAll("a[href]");
      links.forEach(a => {
        const href = a.getAttribute("href");
        if (href === path || (path === "index.html" && href === "index.html")) {
          a.setAttribute("aria-current", "page");
        }
        // close menu on link click (mobile)
        a.addEventListener("click", () => closeMenu(menu, toggle, backdrop));
      });
    }

    // mobile menu toggle
    if (toggle && menu) {
      toggle.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const isHidden = menu.hasAttribute("hidden");
        if (isHidden) openMenu(menu, toggle, backdrop);
        else closeMenu(menu, toggle, backdrop);
      });

      // click on backdrop closes menu
      backdrop.addEventListener("click", () => closeMenu(menu, toggle, backdrop));

      // ESC to close
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
}

function closeMenu(menu, toggle, backdrop) {
  if (!menu.hasAttribute("hidden")) menu.setAttribute("hidden", "");
  toggle.setAttribute("aria-expanded", "false");
  if (!backdrop.hasAttribute("hidden")) backdrop.setAttribute("hidden", "");
}