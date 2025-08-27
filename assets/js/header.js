// assets/js/header.js
fetch("partials/header.html")
  .then(res => res.text())
  .then(html => {
    // inject at the top of <body>
    const mount = document.getElementById("header");
    if (mount) mount.innerHTML = html;
    else document.body.insertAdjacentHTML("afterbegin", html);

    // set active nav item (aria-current + optional class)
    const path = location.pathname.split("/").pop() || "index.html";
    const menu = document.getElementById("primary-menu");
    if (menu) {
      const links = menu.querySelectorAll("a[href]");
      links.forEach(a => {
        const href = a.getAttribute("href");
        if (href === path || (path === "index.html" && href === "index.html")) {
          a.setAttribute("aria-current", "page");
        }
      });
    }

    // mobile menu toggle
    const toggle = document.querySelector(".menu-toggle");
    if (toggle && menu) {
      toggle.addEventListener("click", () => {
        const isHidden = menu.hasAttribute("hidden");
        if (isHidden) menu.removeAttribute("hidden");
        else menu.setAttribute("hidden", "");
        toggle.setAttribute("aria-expanded", String(isHidden));
      });
    }
  })
  .catch(err => console.error("Error loading header:", err));