(function () {
  const K = window.KARAOKE;
  if (!K || typeof K.initPlaybackControls !== "function") {
    console.error("karaoke-audience-host-local.js: load karaoke-core.js first.");
    return;
  }

  const q = new URLSearchParams(window.location.search);
  const API_BASE = (q.get("api") || window.KARAOKE_API_BASE || "http://127.0.0.1:8787").replace(/\/$/, "");
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

  const PB = K.initPlaybackControls();

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

  function setStatus(t) {
    if (statusEl) statusEl.textContent = t || "";
  }

  function listenerUrl() {
    const room = (roomIdEl.value || "room1").trim();
    const base =
      window.location.origin +
      window.location.pathname.replace("host-audience-local.html", "listener-audience-local.html");
    const u = new URL(base);
    u.searchParams.set("api", API_BASE);
    u.searchParams.set("room", room);
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
      o.textContent = (it.title || it.job_id) + " — " + it.job_id;
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
