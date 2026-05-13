(function () {
  const K = window.KARAOKE;
  if (!K || typeof K.initPlaybackControls !== "function") {
    console.error("karaoke-host.js: load karaoke-core.js first.");
    return;
  }

  if (typeof window.karaokeResolveApiBase !== "function") {
    console.error("karaoke-host.js: load karaoke-api-base.js first.");
    return;
  }

  (async function main() {
    const API_BASE = await window.karaokeResolveApiBase();
    const endpoints = {
      list: API_BASE + "/api/list",
      lyrics: API_BASE + "/api/lyrics",
      session: API_BASE + "/api/audience/session",
    };

    const roomIdEl = document.getElementById("roomId");
    const hostNameEl = document.getElementById("hostName");
    const songPickEl = document.getElementById("songPick");
    const statusEl = document.getElementById("status");
    const vocalsEl = document.getElementById("vocalsEl");
    const listenerUrlEl = document.getElementById("listenerUrl");
    const refreshBtn = document.getElementById("refreshList");
    const publishBtn = document.getElementById("publishNow");

    const PB = K.initPlaybackControls({ autoInitDevices: true });

    let items = [];
    let current = null;
    let currentLyrics = { synced: false, lrc: "", text: "" };
    let timer = null;

    function apiOrigin() {
      try {
        return new URL(API_BASE).origin;
      } catch {
        return "";
      }
    }

    /** Match stem URL host to API so LAN/ngrok works when list returns 127.0.0.1 links. */
    function resolveStemUrl(u) {
      if (!u || typeof u !== "string") return u;
      const origin = apiOrigin();
      if (!origin) return u;
      try {
        const p = new URL(u, origin);
        return origin + p.pathname + p.search + p.hash;
      } catch {
        return u;
      }
    }

    /** Same rules as karaoke-player-folder-local-root.js (folder song picker). */
    function normalizeHumanTitle(raw) {
      let s = String(raw || "").trim();
      if (!s) return "";
      s = s.replace(/[_\s-]*(?:64|96|128|160|192|256|320)\s*kbps[_\s-]*/gi, " ");
      s = s.replace(/\.(mp3|wav|m4a|flac|aac|ogg)$/i, "");
      s = s.replace(/[_]+/g, " ");
      return s.replace(/\s{2,}/g, " ").trim();
    }

    function buildSongDisplayLabel(item) {
      const title = normalizeHumanTitle((item && item.title) || "");
      const artist = (item && item.artist && String(item.artist).trim()) || "";
      const movie = (item && item.movie && String(item.movie).trim()) || "";
      const language = (item && item.language && String(item.language).trim()) || "";
      const category = (item && item.category && String(item.category).trim()) || "";
      const tags = Array.isArray(item && item.tags)
        ? item.tags.slice(0, 2).map((x) => String(x || "").trim()).filter(Boolean)
        : [];
      const primary = title || item.job_id;
      const meta = [];
      if (artist) meta.push(artist);
      if (movie) meta.push(movie);
      if (language) meta.push(language);
      if (category) meta.push(category);
      if (tags.length) meta.push(tags.join(", "));
      return meta.length ? primary + " — " + meta.join(" | ") : primary;
    }

    function setStatus(t) {
      if (statusEl) statusEl.textContent = t || "";
    }

    function listenerUrl() {
      const room = (roomIdEl.value || "room1").trim();
      const u = new URL(window.location.href);
      u.pathname = u.pathname.replace(/host\.html$/i, "audience.html");
      u.searchParams.delete("api");
      u.searchParams.set("room", room);
      try {
        const pageOrigin = window.location.origin.replace(/\/$/, "");
        if (API_BASE !== pageOrigin) {
          u.searchParams.set("api", API_BASE);
        }
      } catch (_) {
        /* ignore */
      }
      return u.toString();
    }

    async function loadSongs() {
      setStatus("Loading songs...");
      const r = await fetch(endpoints.list, { mode: "cors" });
      const d = await r.json();
      items = Array.isArray(d.items) ? d.items : [];
      songPickEl.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = items.length ? "Select a song..." : "No completed songs";
      songPickEl.appendChild(ph);
      items.forEach((it) => {
        const o = document.createElement("option");
        o.value = it.job_id;
        const labelBase = buildSongDisplayLabel(it);
        const dup = items.filter((x) => buildSongDisplayLabel(x) === labelBase).length;
        o.textContent = dup > 1 ? labelBase + " [" + it.job_id + "]" : labelBase;
        songPickEl.appendChild(o);
      });
      listenerUrlEl.value = listenerUrl();
      setStatus(items.length ? "Loaded " + items.length + " song(s)." : "No songs found.");
    }

    async function loadLyrics(jobId) {
      const u = new URL(endpoints.lyrics);
      u.searchParams.set("job_id", jobId);
      const r = await fetch(u.toString(), { mode: "cors" });
      const d = await r.json();
      currentLyrics = {
        synced: !!d.synced,
        lrc: d.lrc || "",
        text: d.text || "",
      };
    }

    async function publishSession() {
      const room = (roomIdEl.value || "").trim();
      if (!room || !current) return;
      const body = {
        room_id: room,
        host_name: (hostNameEl.value || "").trim(),
        job_id: current.job_id,
        title: current.title || current.job_id,
        vocals_url: current.vocals_url || "",
        band_url: current.band_url || "",
        playing: vocalsEl && !vocalsEl.paused,
        position_sec: vocalsEl ? vocalsEl.currentTime || 0 : 0,
        synced: !!currentLyrics.synced,
        lrc: currentLyrics.lrc || "",
        text: currentLyrics.text || "",
      };
      await fetch(endpoints.session, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify(body),
        mode: "cors",
      });
    }

    songPickEl.addEventListener("change", async function () {
      const id = songPickEl.value;
      current = items.find((x) => x.job_id === id) || null;
      if (!current) {
        PB.setSources("", "");
        setStatus("");
        return;
      }
      const v = resolveStemUrl(current.vocals_url || "");
      const b = resolveStemUrl(current.band_url || "");
      PB.setSources(v, b);
      PB.showTitle(current.title || current.job_id);
      await loadLyrics(current.job_id);
      await publishSession();
      setStatus("Ready: " + (current.title || current.job_id) + " — host hears vocals + band.");
    });

    refreshBtn.addEventListener("click", function () {
      loadSongs().catch((e) => setStatus(String(e)));
    });
    publishBtn.addEventListener("click", function () {
      publishSession().then(() => setStatus("Published.")).catch((e) => setStatus(String(e)));
    });

    [roomIdEl, hostNameEl].forEach((el) => {
      el &&
        el.addEventListener("input", function () {
          listenerUrlEl.value = listenerUrl();
        });
    });

    if (vocalsEl) {
      vocalsEl.addEventListener("play", function () {
        publishSession().catch(() => {});
      });
      vocalsEl.addEventListener("pause", function () {
        publishSession().catch(() => {});
      });
      vocalsEl.addEventListener("seeked", function () {
        publishSession().catch(() => {});
      });
    }

    timer = setInterval(function () {
      publishSession().catch(() => {});
    }, 1000);

    loadSongs().catch((e) => setStatus(String(e)));
  })();
})();
