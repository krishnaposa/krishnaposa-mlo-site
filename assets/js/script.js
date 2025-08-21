/* =========================================================
   Krish Posa site JS
   - Mobile nav toggle with a11y
   - Close on outside click / Escape
   - Smooth scroll for same-page anchors (respects reduce motion)
   ========================================================= */

// 0) Mark JS-enabled for any CSS hooks
document.documentElement.classList.remove('no-js');
document.documentElement.classList.add('js');

// 1) Mobile nav toggle (accessible)
(function(){
  const btn  = document.querySelector('.menu-toggle');
  const menu = document.querySelector('.menu');
  if (!btn || !menu) return;

  // Ensure ARIA wiring even if not present in HTML
  if (!btn.hasAttribute('aria-controls')) btn.setAttribute('aria-controls', 'primary-menu');
  if (!menu.id) menu.id = 'primary-menu';
  btn.setAttribute('aria-expanded', 'false');

  const openMenu = () => {
    menu.classList.add('show');
    btn.setAttribute('aria-expanded', 'true');
  };
  const closeMenu = () => {
    menu.classList.remove('show');
    btn.setAttribute('aria-expanded', 'false');
  };
  const toggleMenu = (e) => {
    e.stopPropagation();
    const isOpen = menu.classList.contains('show');
    isOpen ? closeMenu() : openMenu();
  };

  btn.addEventListener('click', toggleMenu);

  // Close when clicking outside the menu
  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('show')) return;
    const clickInsideMenu = menu.contains(e.target) || e.target === btn;
    if (!clickInsideMenu) closeMenu();
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && menu.classList.contains('show')) {
      closeMenu();
      btn.focus();
    }
  });

  // Close when a menu link is clicked (useful on mobile)
  menu.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (!link) return;
    // Only close if it’s a same-page navigation or any link on small screens
    if (window.matchMedia('(max-width: 900px)').matches) closeMenu();
  });

  // Optional: close on resize to desktop
  let lastWide = window.matchMedia('(min-width: 901px)').matches;
  window.addEventListener('resize', () => {
    const nowWide = window.matchMedia('(min-width: 901px)').matches;
    if (nowWide && !lastWide) closeMenu();
    lastWide = nowWide;
  });
})();

// 2) Smooth scroll for same-page anchors (respects reduced motion)
(function(){
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const links = document.querySelectorAll('a[href^="#"]:not([href="#"])');

  function smoothScrollTo(target) {
    const el = document.querySelector(target);
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY - 12; // small offset
    if (prefersReduced) {
      window.scrollTo(0, top);
    } else {
      window.scrollTo({ top, behavior: 'smooth' });
    }
    // Move focus for accessibility
    el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
  }

  links.forEach(a => {
    a.addEventListener('click', (e) => {
      const href = a.getAttribute('href');
      const url = new URL(href, window.location.href);
      if (url.pathname.replace(/\/$/, '') !== window.location.pathname.replace(/\/$/, '')) return;
      if (!url.hash) return;
      const target = url.hash;
      const targetEl = document.querySelector(target);
      if (!targetEl) return;

      e.preventDefault();
      smoothScrollTo(target);
      history.pushState(null, '', target);
    });
  });
})();

// 3) (Optional) Auto-apply lazy loading to imgs missing it
(function(){
  document.querySelectorAll('img:not([loading])').forEach(img => {
    img.setAttribute('loading', 'lazy');
    img.setAttribute('decoding', 'async');
  });
})();