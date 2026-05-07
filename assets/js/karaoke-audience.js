(function () {
  if (typeof window.karaokeResolveApiBase !== "function") {
    console.error("karaoke-audience.js: load karaoke-api-base.js first.");
    return;
  }

  (async function main() {
    const API_BASE = await window.karaokeResolveApiBase();
    const endpoints = { session: API_BASE + "/api/audience/session" };

    const q = new URLSearchParams(window.location.search);
    const roomIdEl = document.getElementById("roomId");
    const joinBtn = document.getElementById("joinBtn");
    const statusEl = document.getElementById("status");
    const vocalsEl = document.getElementById("vocalsEl");
    const plainEl = document.getElementById("lyricsPlain");
    const syncedEl = document.getElementById("lyricsSynced");

    let timer = null;
    let currentJob = "";
    let lrcLines = [];

    function setStatus(t) {
      if (statusEl) statusEl.textContent = t || "";
    }

    function parseLrc(s) {
      const lines = [];
      String(s || "")
        .split(/\r?\n/)
        .forEach((ln) => {
          const m = ln.match(/^\[(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?\](.*)$/);
          if (!m) return;
          const t = Number(m[1]) * 60 + Number(m[2]) + Number(m[3] || 0) / 100;
          lines.push({ t: t, text: (m[4] || "").trim() || " " });
        });
      lines.sort((a, b) => a.t - b.t);
      return lines;
    }

    function renderSynced(lines) {
      syncedEl.innerHTML = "";
      lines.forEach((x, i) => {
        const div = document.createElement("div");
        div.className = "line";
        div.dataset.idx = String(i);
        div.textContent = x.text || " ";
        syncedEl.appendChild(div);
      });
    }

    function tickLyrics() {
      if (!lrcLines.length) return;
      const t = vocalsEl.currentTime || 0;
      let idx = 0;
      for (let i = 0; i < lrcLines.length; i++) {
        if (lrcLines[i].t <= t) idx = i;
        else break;
      }
      const els = syncedEl.querySelectorAll(".line");
      els.forEach((el, i) => el.classList.toggle("active", i === idx));
      const active = els[idx];
      if (active && typeof active.scrollIntoView === "function") active.scrollIntoView({ block: "nearest" });
    }

    async function poll() {
      const room = (roomIdEl.value || "").trim();
      if (!room) return;
      const u = new URL(endpoints.session);
      u.searchParams.set("room_id", room);
      const r = await fetch(u.toString(), { mode: "cors" });
      const d = await r.json();
      if (!d.found || !d.session) {
        setStatus("Waiting for host...");
        return;
      }
      const s = d.session;
      setStatus("Connected to " + (s.host_name || "host") + " / " + (s.title || s.job_id || ""));
      if (s.job_id && s.job_id !== currentJob) {
        currentJob = s.job_id;
        vocalsEl.src = s.vocals_url || "";
        if (s.synced && s.lrc) {
          lrcLines = parseLrc(s.lrc);
          plainEl.hidden = true;
          syncedEl.hidden = false;
          renderSynced(lrcLines);
        } else {
          lrcLines = [];
          syncedEl.hidden = true;
          plainEl.hidden = false;
          plainEl.textContent = (s.text || "").trim() || "—";
        }
      }
      const pos = Number(s.position_sec || 0);
      if (Math.abs((vocalsEl.currentTime || 0) - pos) > 0.8) {
        try {
          vocalsEl.currentTime = pos;
        } catch (_) {
          /* ignore */
        }
      }
      if (s.playing) {
        if (vocalsEl.paused) vocalsEl.play().catch(() => {});
      } else if (!vocalsEl.paused) {
        vocalsEl.pause();
      }
    }

    joinBtn.addEventListener("click", function () {
      if (timer) clearInterval(timer);
      poll().catch((e) => setStatus(String(e)));
      timer = setInterval(function () {
        poll().catch(() => {});
      }, 1000);
    });

    vocalsEl.addEventListener("timeupdate", tickLyrics);
    const roomFromQuery = (q.get("room") || "").trim();
    if (roomFromQuery) roomIdEl.value = roomFromQuery;
  })();
})();
