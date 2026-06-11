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
    const playlistListEl = document.getElementById("playlistList");
    const playlistAddBtn = document.getElementById("playlistAdd");
    const playlistPlayBtn = document.getElementById("playlistPlay");
    const playlistClearBtn = document.getElementById("playlistClear");
    const playlistStatusEl = document.getElementById("playlistStatus");

    const isPhone = typeof K.isCoarseMobile === "function" && K.isCoarseMobile();
    if (isPhone) {
      document.documentElement.classList.add("karaoke-mobile-host");
      const mobNotice = document.getElementById("hostMobileNotice");
      if (mobNotice) mobNotice.hidden = false;
    }

    const PB = K.initPlaybackControls({
      autoInitDevices: !isPhone,
      preferMobileMix: isPhone,
    });

    let items = [];
    let current = null;
    let currentLyrics = { synced: false, lrc: "", text: "" };
    let timer = null;
    let hostLrcCleanup = null;
    let hostLrcParsed = [];
    let playlist = [];
    let playlistIndex = -1;
    let playlistPlaying = false;
    let playlistAdvancing = false;
    let dragFromIdx = -1;

    function escHtml(s) {
      const d = document.createElement("div");
      d.textContent = String(s || "");
      return d.innerHTML;
    }

    function setPlaylistStatus(t) {
      if (playlistStatusEl) playlistStatusEl.textContent = t || "";
    }

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

    function renderPlaylist() {
      if (!playlistListEl) return;
      playlistListEl.innerHTML = "";
      playlist.forEach((item, idx) => {
        const li = document.createElement("li");
        li.className = "host-playlist-item";
        li.draggable = true;
        li.dataset.idx = String(idx);
        if (playlistPlaying && idx === playlistIndex) {
          li.classList.add("is-playing");
        }
        const outHint =
          !PB.isMobileMix && (item.vocals_sink || item.band_sink)
            ? '<span class="host-playlist-outs tiny" title="Outputs saved when added">🔊</span>'
            : "";
        li.innerHTML =
          '<span class="host-playlist-grip" aria-hidden="true">⋮⋮</span>' +
          '<span class="host-playlist-num">' + (idx + 1) + "</span>" +
          '<span class="host-playlist-label">' + escHtml(buildSongDisplayLabel(item)) + "</span>" +
          outHint +
          '<button type="button" class="host-playlist-remove" data-idx="' + idx + '" aria-label="Remove from playlist">×</button>';

        li.addEventListener("dragstart", function (e) {
          dragFromIdx = idx;
          li.classList.add("dragging");
          if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", String(idx));
          }
        });
        li.addEventListener("dragend", function () {
          dragFromIdx = -1;
          li.classList.remove("dragging");
          playlistListEl.querySelectorAll(".host-playlist-item").forEach(function (el) {
            el.classList.remove("drag-over");
          });
        });
        li.addEventListener("dragover", function (e) {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
          li.classList.add("drag-over");
        });
        li.addEventListener("dragleave", function () {
          li.classList.remove("drag-over");
        });
        li.addEventListener("drop", function (e) {
          e.preventDefault();
          li.classList.remove("drag-over");
          const from = dragFromIdx;
          const to = idx;
          if (from < 0 || from === to) return;
          const moved = playlist.splice(from, 1)[0];
          playlist.splice(to, 0, moved);
          if (playlistPlaying && playlistIndex === from) {
            playlistIndex = to;
          } else if (playlistPlaying && playlistIndex > from && playlistIndex <= to) {
            playlistIndex -= 1;
          } else if (playlistPlaying && playlistIndex < from && playlistIndex >= to) {
            playlistIndex += 1;
          }
          renderPlaylist();
          setPlaylistStatus("Reordered — " + playlist.length + " song(s).");
        });

        const removeBtn = li.querySelector(".host-playlist-remove");
        removeBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          removeFromPlaylist(idx);
        });

        li.addEventListener("dblclick", function () {
          loadSongByItem(playlist[idx], { syncPick: true }).catch(function (err) {
            setStatus(String(err));
          });
        });

        playlistListEl.appendChild(li);
      });
    }

    function removeFromPlaylist(idx) {
      if (idx < 0 || idx >= playlist.length) return;
      const wasPlaying = playlistPlaying && playlistIndex === idx;
      playlist.splice(idx, 1);
      if (!playlist.length) {
        playlistPlaying = false;
        playlistIndex = -1;
        setPlaylistStatus("Playlist cleared.");
      } else if (playlistPlaying) {
        if (playlistIndex > idx) playlistIndex -= 1;
        else if (wasPlaying) {
          playlistIndex = Math.min(playlistIndex, playlist.length - 1);
          if (playlistPlaying) {
            playPlaylistFrom(playlistIndex).catch(function (e) {
              setStatus(String(e));
            });
          }
        }
        setPlaylistStatus(playlist.length + " song(s) in queue.");
      } else {
        setPlaylistStatus(playlist.length + " song(s) in queue.");
      }
      renderPlaylist();
    }

    function addToPlaylist() {
      const id = songPickEl && songPickEl.value;
      if (!id) {
        setPlaylistStatus("Select a song above first.");
        return;
      }
      const item = items.find(function (x) {
        return x.job_id === id;
      });
      if (!item) {
        setPlaylistStatus("Song not found — refresh the list.");
        return;
      }
      if (
        playlist.some(function (x) {
          return x.job_id === id;
        })
      ) {
        setPlaylistStatus("Already in playlist.");
        return;
      }
      const outs = typeof PB.getOutputIds === "function" ? PB.getOutputIds() : {};
      playlist.push(
        Object.assign({}, item, {
          vocals_sink: outs.vocals || "",
          band_sink: outs.band || "",
        })
      );
      renderPlaylist();
      setPlaylistStatus("Added — " + playlist.length + " song(s) queued.");
    }

    async function applyPlaylistOutputs(item) {
      if (!item || typeof PB.setOutputIds !== "function") return;
      const v = item.vocals_sink;
      const b = item.band_sink;
      if (!v && !b) return;
      try {
        await PB.setOutputIds({
          vocals: v || undefined,
          band: b || undefined,
        });
      } catch (e) {
        console.warn("applyPlaylistOutputs", e);
      }
    }

    function snapshotCurrentOutputsToPlaylistItem(item) {
      if (!item || typeof PB.getOutputIds !== "function") return;
      const outs = PB.getOutputIds();
      item.vocals_sink = outs.vocals || "";
      item.band_sink = outs.band || "";
    }

    async function loadSongByItem(item, opts) {
      const o = opts || {};
      if (!item) return;
      current = item;
      if (o.syncPick && songPickEl) {
        songPickEl.value = item.job_id;
      }
      if (o.usePlaylistOutputs !== false && (item.vocals_sink || item.band_sink)) {
        await applyPlaylistOutputs(item);
      }
      const v = resolveStemUrl(item.vocals_url || "");
      const b = resolveStemUrl(item.band_url || "");
      PB.setSources(v, b);
      if (typeof PB.applySinks === "function") {
        await PB.applySinks();
      }
      PB.showTitle(item.title || item.job_id);
      await loadLyrics(item.job_id);
      await publishSession();
      renderPlaylist();
      const routing =
        !PB.isMobileMix && (item.vocals_sink || item.band_sink)
          ? " — vocals/band on saved outputs"
          : " — host hears vocals + band.";
      setStatus("Ready: " + (item.title || item.job_id) + routing);
    }

    async function playPlaylistFrom(startIdx) {
      if (!playlist.length) {
        setPlaylistStatus("Add songs to the playlist first.");
        return;
      }
      const idx = Math.max(0, Math.min(startIdx, playlist.length - 1));
      playlistPlaying = true;
      playlistIndex = idx;
      playlistAdvancing = true;
      try {
        await loadSongByItem(playlist[idx], { syncPick: true, usePlaylistOutputs: true });
        if (typeof PB.play === "function") {
          await PB.play({ fromStart: true });
        } else {
          document.getElementById("play")?.click();
        }
        setPlaylistStatus(
          "Playing " + (idx + 1) + " of " + playlist.length + ": " + buildSongDisplayLabel(playlist[idx])
        );
      } finally {
        playlistAdvancing = false;
      }
    }

    async function advancePlaylist() {
      if (!playlistPlaying || playlistAdvancing) return;
      const next = playlistIndex + 1;
      if (next >= playlist.length) {
        playlistPlaying = false;
        playlistIndex = -1;
        renderPlaylist();
        setPlaylistStatus("Playlist finished.");
        setStatus("Playlist finished.");
        return;
      }
      playlistAdvancing = true;
      try {
        PB.pause();
        await playPlaylistFrom(next);
      } catch (e) {
        playlistPlaying = false;
        setStatus(String(e));
        setPlaylistStatus("Playlist stopped: " + String(e));
      } finally {
        playlistAdvancing = false;
      }
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
      if (!playlistAdvancing) {
        playlistPlaying = false;
        playlistIndex = -1;
        renderPlaylist();
      }
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
      await loadSongByItem(current, { syncPick: false });
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

    playlistAddBtn?.addEventListener("click", addToPlaylist);
    playlistPlayBtn?.addEventListener("click", function () {
      playPlaylistFrom(0).catch(function (e) {
        setStatus(String(e));
        setPlaylistStatus(String(e));
      });
    });
    playlistClearBtn?.addEventListener("click", function () {
      playlist = [];
      playlistPlaying = false;
      playlistIndex = -1;
      renderPlaylist();
      setPlaylistStatus("Playlist cleared.");
    });

    const playlistSaveOutsBtn = document.getElementById("playlistSaveOutputs");
    playlistSaveOutsBtn?.addEventListener("click", function () {
      if (!playlist.length) {
        setPlaylistStatus("Playlist is empty.");
        return;
      }
      playlist.forEach(function (item) {
        snapshotCurrentOutputsToPlaylistItem(item);
      });
      renderPlaylist();
      setPlaylistStatus("Saved current vocals/band outputs for all " + playlist.length + " song(s).");
    });

    function onOutputChangeDuringPlaylist() {
      if (typeof PB.applySinks === "function") {
        PB.applySinks().catch(function () {});
      }
      if (playlistPlaying && playlistIndex >= 0 && playlist[playlistIndex]) {
        snapshotCurrentOutputsToPlaylistItem(playlist[playlistIndex]);
      }
    }
    document.getElementById("vocalsOut")?.addEventListener("change", onOutputChangeDuringPlaylist);
    document.getElementById("bandOut")?.addEventListener("change", onOutputChangeDuringPlaylist);

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
      vocalsEl.addEventListener("ended", function () {
        if (playlistPlaying && !playlistAdvancing) {
          advancePlaylist().catch(function (e) {
            setStatus(String(e));
          });
        }
      });
    }

    timer = setInterval(function () {
      publishSession().catch(() => {});
    }, 1000);

    renderPlaylist();
    loadSongs().catch((e) => setStatus(String(e)));
  })();
})();
