/* Auto-blog index: add posts here. Newest first. */
const POSTS = [
  {
    title: "Mortgage Rates Slide to 10‑Month Low — What It Means for Atlanta Buyers",
    url: "blog-mortgage-rates.html",
    date: "2025-08-21",
    excerpt:
      "Mortgage rates dipped to a 10‑month low. Here’s how that changes buying power and refinance math for Atlanta borrowers—and why this window may not last.",
    tags: ["Rates", "Atlanta", "Refinance"]
  },
  // Example future post:
  // {
  //   title: "First‑Time Buyer Mistakes to Avoid in Georgia",
  //   url: "blog-first-time-buyer-mistakes.html",
  //   date: "2025-09-02",
  //   excerpt: "From budgeting to inspections—what to know before you write an offer in today’s market.",
  //   tags: ["First‑Time Buyers", "Georgia"]
  // }
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