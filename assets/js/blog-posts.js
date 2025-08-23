/* Auto-blog index: add posts here. Newest first. */
const POSTS = [
  {
    title: "Mortgage Rates Slide to 10-Month Low — What It Means for Atlanta Buyers",
    url: "blog-mortgage-rates.html",
    date: "2025-08-21",
    excerpt:
      "Mortgage rates dipped to a 10-month low. Here’s how that changes buying power and refinance math for Atlanta borrowers—and why this window may not last.",
    tags: ["Rates", "Atlanta", "Refinance"]
  },
  {
    title: "The Truth About IUL: Why Design Matters More Than Anything",
    url: "blog-iul-truth.html",
    date: "2025-08-22",
    excerpt:
      "Indexed Universal Life (IUL) is one of the most misunderstood financial tools. Learn why most IULs fail and the 6 principles that separate strong designs from ticking time bombs.",
    tags: ["IUL", "Insurance", "Wealth"]
  },
  {
    title: "My 5-Year Experience with Prosper P2P Investing",
    url: "blog-prosper-returns.html",
    date: "2025-08-23",
    excerpt:
      "After five years on Prosper, my returns tell a different story than the advertised 8–12%. Here’s how defaults, fees, and prepayments cut my net return to 3.8%.",
    tags: ["Investing", "P2P Lending", "Personal Finance"]
 }
  // Add future posts below this line
];
/* Render cards */
(function () {
  const wrap = document.getElementById("blog-list");
  if (!wrap || !Array.isArray(POSTS)) return;

  // Utility: format date as Month D, YYYY
  function fmt(d) {
    try {
      const dt = new Date(d + "T00:00:00");
      return dt.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
    } catch {
      return d;
    }
  }

  POSTS.forEach((p) => {
    const card = document.createElement("article");
    card.className = "card";

    const h3 = document.createElement("h3");
    h3.textContent = p.title;

    const meta = document.createElement("p");
    meta.className = "small";
    meta.textContent = fmt(p.date) + (p.tags?.length ? " · " + p.tags.join(" • ") : "");

    const ex = document.createElement("p");
    ex.textContent = p.excerpt;

    const link = document.createElement("a");
    link.href = p.url;
    link.textContent = "Read More →";

    card.appendChild(h3);
    card.appendChild(meta);
    card.appendChild(ex);
    card.appendChild(link);
    wrap.appendChild(card);
  });
})();