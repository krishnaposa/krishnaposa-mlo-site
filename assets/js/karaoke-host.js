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
    const clearFiltersBtn = document.getElementById("clearFilters");
    const filterSearchEl = document.getElementById("filterSearch");
    const filterMovieEl = document.getElementById("filterMovie");
    const filterSingerEl = document.getElementById("filterSinger");
    const publishBtn = document.getElementById("publishNow");
    const hostLyricsPlain = document.getElementById("hostLyricsPlain");
    const hostLyricsSynced = document.getElementById("hostLyricsSynced");

    const PB = K.initPlaybackControls({ autoInitDevices: true });

    let items = [];
    let current = null;
    let currentLyrics = { synced: false, lrc: "", text: "" };
    let timer = null;
    let hostLrcCleanup = null;
    let hostLrcParsed = [];

    function stopHostLyricsSync() {
      if (typeof hostLrcCleanup === "function") {
        try {
          hostLrcCleanup();
        } catch (_) {
          /* ignore */
        }
      }
      hostLrcCleanup = null;
      hostLrcParsed = [];
    }

    function renderHostLrcLines(container, lines) {
      container.innerHTML = "";
      lines.forEach((line, i) => {
        const div = document.createElement("div");
        div.className = "line";
        div.dataset.idx = String(i);
        div.textContent = line.text || " ";
        container.appendChild(div);
      });
    }

    function tickHostLyrics() {
      if (!hostLrcParsed.length || !hostLyricsSynced || hostLyricsSynced.hidden || !vocalsEl) return;
      const t = vocalsEl.currentTime || 0;
      let idx = 0;
      for (let i = 0; i < hostLrcParsed.length; i++) {
        if (hostLrcParsed[i].t <= t) idx = i;
        else break;
      }
      const els = hostLyricsSynced.querySelectorAll(".line");
      els.forEach((el, i) => el.classList.toggle("active", i === idx));
      const active = els[idx];
      if (active && typeof active.scrollIntoView === "function") {
        active.scrollIntoView({ block: "nearest" });
      }
    }

    function startHostLyricsSync(parsed) {
      stopHostLyricsSync();
      hostLrcParsed = parsed;
      if (!vocalsEl || !parsed.length) return;
      function tick() {
        tickHostLyrics();
      }
      vocalsEl.addEventListener("timeupdate", tick);
      vocalsEl.addEventListener("seeked", tick);
      hostLrcCleanup = function () {
        vocalsEl.removeEventListener("timeupdate", tick);
        vocalsEl.removeEventListener("seeked", tick);
      };
      tick();
    }

    function applyHostLyricsUI() {
      if (!hostLyricsPlain || !hostLyricsSynced) return;
      const hasLrc = currentLyrics.synced && String(currentLyrics.lrc || "").trim();
      if (hasLrc) {
        const parsed = K.parseLRC(currentLyrics.lrc);
        if (parsed.length) {
          hostLyricsPlain.hidden = true;
          hostLyricsSynced.hidden = false;
          renderHostLrcLines(hostLyricsSynced, parsed);
          startHostLyricsSync(parsed);
          return;
        }
      }
      stopHostLyricsSync();
      hostLyricsSynced.hidden = true;
      hostLyricsSynced.innerHTML = "";
      hostLyricsPlain.hidden = false;
      const plain = String(currentLyrics.text || "").trim();
      hostLyricsPlain.textContent = plain ? plain : "—";
    }

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

    function singerLabel(item) {
      const singers = Array.isArray(item && item.singers)
        ? item.singers.map((x) => String(x || "").trim()).filter(Boolean)
        : [];
      if (singers.length) return singers.join(", ");
      return (item && item.artist && String(item.artist).trim()) || "";
    }

    function buildSongDisplayLabel(item) {
      const title = normalizeHumanTitle((item && item.title) || "");
      const movie = (item && item.movie && String(item.movie).trim()) || "";
      const singer = singerLabel(item);
      const primary = title || item.job_id;
      const meta = [];
      if (movie) meta.push(movie);
      if (singer) meta.push(singer);
      return meta.length ? primary + " — " + meta.join(" | ") : primary;
    }

    function buildListUrl() {
      const url = new URL(endpoints.list);
      const setIf = (key, el) => {
        const v = el && String(el.value || "").trim();
        if (v) url.searchParams.set(key, v);
        else url.searchParams.delete(key);
      };
      setIf("q", filterSearchEl);
      setIf("movie", filterMovieEl);
      setIf("singer", filterSingerEl);
      return url.toString();
    }

    function populateSongPick(list) {
      const prev = songPickEl ? songPickEl.value : "";
      if (!songPickEl) return;
      songPickEl.innerHTML = "";
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = list.length ? "Select a song..." : "No songs match filters";
      songPickEl.appendChild(ph);
      list.forEach((it) => {
        const o = document.createElement("option");
        o.value = it.job_id;
        const labelBase = buildSongDisplayLabel(it);
        const dup = list.filter((x) => buildSongDisplayLabel(x) === labelBase).length;
        o.textContent = dup > 1 ? labelBase + " [" + it.job_id + "]" : labelBase;
        songPickEl.appendChild(o);
      });
      if (prev && list.some((x) => x.job_id === prev)) {
        songPickEl.value = prev;
      } else if (list.length === 1) {
        songPickEl.value = list[0].job_id;
        songPickEl.dispatchEvent(new Event("change"));
      } else if (prev && !list.some((x) => x.job_id === prev)) {
        songPickEl.value = "";
        songPickEl.dispatchEvent(new Event("change"));
      }
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
      const r = await fetch(buildListUrl(), { mode: "cors" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      items = Array.isArray(d.items) ? d.items : [];
      populateSongPick(items);
      if (listenerUrlEl) listenerUrlEl.value = listenerUrl();
      const q = filterSearchEl && filterSearchEl.value.trim();
      const mov = filterMovieEl && filterMovieEl.value.trim();
      const sing = filterSingerEl && filterSingerEl.value.trim();
      const filt =
        q || mov || sing
          ? " (filters: " +
            [
              q ? "search=" + q : "",
              mov ? "movie=" + mov : "",
              sing ? "singer=" + sing : "",
            ]
              .filter(Boolean)
              .join(", ") +
            ")"
          : "";
      setStatus(
        items.length
          ? "Loaded " + items.length + " song(s)." + filt
          : "No songs match" + (filt || " — try clearing filters.")
      );
    }

    async function loadLyrics(jobId) {
      currentLyrics = { synced: false, lrc: "", text: "" };
      applyHostLyricsUI();
      try {
        const u = new URL(endpoints.lyrics);
        u.searchParams.set("job_id", jobId);
        const r = await fetch(u.toString(), { mode: "cors" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        currentLyrics = {
          synced: !!d.synced,
          lrc: d.lrc || "",
          text: d.text || "",
        };
      } catch (e) {
        console.warn("loadLyrics", e);
        currentLyrics = { synced: false, lrc: "", text: "" };
      }
      applyHostLyricsUI();
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
        stopHostLyricsSync();
        currentLyrics = { synced: false, lrc: "", text: "" };
        if (hostLyricsPlain) {
          hostLyricsPlain.hidden = false;
          hostLyricsPlain.textContent = "—";
        }
        if (hostLyricsSynced) {
          hostLyricsSynced.hidden = true;
          hostLyricsSynced.innerHTML = "";
        }
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
    if (clearFiltersBtn) {
      clearFiltersBtn.addEventListener("click", function () {
        if (filterSearchEl) filterSearchEl.value = "";
        if (filterMovieEl) filterMovieEl.value = "";
        if (filterSingerEl) filterSingerEl.value = "";
        loadSongs().catch((e) => setStatus(String(e)));
      });
    }
    let filterTimer = null;
    function scheduleFilterReload() {
      if (filterTimer) clearTimeout(filterTimer);
      filterTimer = setTimeout(function () {
        loadSongs().catch((e) => setStatus(String(e)));
      }, 350);
    }
    [filterSearchEl, filterMovieEl, filterSingerEl].forEach(function (el) {
      el &&
        el.addEventListener("input", scheduleFilterReload);
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
