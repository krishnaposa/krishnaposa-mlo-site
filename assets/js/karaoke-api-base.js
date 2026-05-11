/**
 * Resolve karaoke HTTP API base URL.
 * Order: ?api= → window.KARAOKE_API_BASE → GET /api/config (public_base from KARAOKE_LOCAL_PUBLIC_BASE on server)
 * → same origin → http://127.0.0.1:8787
 */
window.karaokeResolveApiBase = async function karaokeResolveApiBase() {
  const sp = new URLSearchParams(window.location.search || "");
  const explicit = (sp.get("api") || "").trim();
  if (explicit) return explicit.replace(/\/$/, "");

  if (typeof window.KARAOKE_API_BASE === "string" && window.KARAOKE_API_BASE.trim()) {
    return window.KARAOKE_API_BASE.trim().replace(/\/$/, "");
  }

  const origin = window.location.origin;
  if (origin && origin !== "null" && window.location.protocol !== "file:") {
    try {
      const r = await fetch(new URL("/api/config", origin).toString(), {
        mode: "cors",
        cache: "no-store",
      });
      if (r.ok) {
        const j = await r.json();
        if (j && j.public_base) {
          let pb = String(j.public_base).replace(/\/$/, "");
          try {
            const u = new URL(pb);
            // HTTPS page + server still advertising http / loopback → mixed content; use same origin as the page.
            if (location.protocol === "https:" && u.protocol !== "https:") {
              return origin.replace(/\/$/, "");
            }
          } catch (_) {
            /* ignore bad public_base */
          }
          return pb;
        }
      }
    } catch (_) {
      /* fall through */
    }
    return origin.replace(/\/$/, "");
  }

  return "http://127.0.0.1:8787";
};
