(function () {
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
  const playBtn = document.getElementById("playBtn");
  const pauseBtn = document.getElementById("pauseBtn");
  const publishBtn = document.getElementById("publishNow");

  let items = [];
  let current = null;
  let currentLyrics = { synced: false, lrc: "", text: "" };
  let timer = null;

  function setStatus(t) { if (statusEl) statusEl.textContent = t || ""; }

  function listenerUrl() {
    const room = (roomIdEl.value || "room1").trim();
    const base = window.location.origin + window.location.pathname.replace("host-audience-local.html", "listener-audience-local.html");
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
    setStatus(items.length ? ("Loaded " + items.length + " song(s).") : "No songs found.");
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
      playing: !vocalsEl.paused,
      position_sec: vocalsEl.currentTime || 0,
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
      vocalsEl.src = "";
      return;
    }
    vocalsEl.src = current.vocals_url || "";
    vocalsEl.currentTime = 0;
    await loadLyrics(current.job_id);
    await publishSession();
    setStatus("Ready: " + (current.title || current.job_id));
  });

  refreshBtn.addEventListener("click", function () { loadSongs().catch((e) => setStatus(String(e))); });
  publishBtn.addEventListener("click", function () { publishSession().then(() => setStatus("Published.")).catch((e) => setStatus(String(e))); });
  playBtn.addEventListener("click", function () { vocalsEl.play(); });
  pauseBtn.addEventListener("click", function () { vocalsEl.pause(); });

  [roomIdEl, hostNameEl].forEach((el) => {
    el && el.addEventListener("input", function () { listenerUrlEl.value = listenerUrl(); });
  });
  vocalsEl.addEventListener("play", function () { publishSession().catch(() => {}); });
  vocalsEl.addEventListener("pause", function () { publishSession().catch(() => {}); });
  vocalsEl.addEventListener("seeked", function () { publishSession().catch(() => {}); });

  timer = setInterval(function () {
    publishSession().catch(() => {});
  }, 1000);

  loadSongs().catch((e) => setStatus(String(e)));
})();
