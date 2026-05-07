# Karaoke local audience — runbook

Audience mode lets a **host** play stems and publish play state + lyrics to a **room**; **listeners** on the same LAN open a link, hear synced vocals (via HTTP audio), and see lyrics (plain or LRC highlight).

This is **HTTP polling + shared session state**, not WebRTC. Good for same Wi‑Fi; scale is browser/network limited.

---

## What runs where

| Component | Purpose |
|-----------|---------|
| `karaoke/local_audience_queue.py` | **Only process you need:** split queue, `/api/list`, `/api/lyrics`, stems, `/api/audience/session`, **and** (by default) static `karaoke/*.html` + `assets/*` on the **same port** |
| `karaoke/host-audience-local.html` + `assets/js/karaoke-audience-host-local.js` | Host UI |
| `karaoke/listener-audience-local.html` + `assets/js/karaoke-audience-listener-local.js` | Listener UI |

**Do not** use `local_folder_queue.py` for audience: it does not expose `/api/audience/session`. Use **`local_audience_queue.py`**.

Static pages are served when `KARAOKE_SERVE_REPO_STATIC` is not disabled (default **on**), same as `local_folder_queue.py`.

---

## Prerequisites

- Python 3.10+ with karaoke deps installed (same as `local_folder_queue`).
- `KARAOKE_LOCAL_ROOT` layout: `input/`, `output/`, `status/`, `lyrics/` (defaults to `~/.karaoke-local` if unset).
- **One port** to open on the firewall for LAN listeners (default **8787**). No separate static-server port required.

---

## Environment (optional)

Same as `local_folder_queue.py`:

| Variable | Default | Notes |
|----------|---------|-------|
| `KARAOKE_LOCAL_ROOT` | `~/.karaoke-local` | Where jobs and stems live |
| `KARAOKE_LOCAL_HOST` | `127.0.0.1` | Bind address; use `0.0.0.0` so phones can reach the server |
| `KARAOKE_LOCAL_PORT` | `8787` | HTTP API + static karaoke pages |
| `KARAOKE_LOCAL_PUBLIC_BASE` | `http://{HOST}:{PORT}` | Stem URLs in `/api/list`; use **LAN** URL when phones load stems |
| `KARAOKE_SERVE_REPO_STATIC` | `1` | Set `0` to disable serving `karaoke/` + `assets/` from this process (then you’d need another static server — not the default workflow). |

For **phones on Wi‑Fi**, bind to all interfaces and set public base to your laptop’s IPv4:

```bash
export KARAOKE_LOCAL_HOST=0.0.0.0
export KARAOKE_LOCAL_PUBLIC_BASE=http://192.168.1.50:8787
```

(Replace `192.168.1.50` with your laptop’s IPv4.)

---

## Startup (single process)

From repo root:

```bash
cd c:/pers/krishnaposa-mlo-site
python karaoke/local_audience_queue.py
```

Confirm logs show `PUBLIC_BASE` / port and that the server is listening. No second `python -m http.server` is required.

---

## URLs (same host and port)

Let `PORT` be your `KARAOKE_LOCAL_PORT` (default `8787`). Replace `LAN_IP` with your machine’s IPv4 when using phones.

**This machine only**

```
http://127.0.0.1:PORT/karaoke/host-audience-local.html?api=http://127.0.0.1:PORT
```

**Host (laptop, phones on LAN)**

```
http://LAN_IP:PORT/karaoke/host-audience-local.html?api=http://LAN_IP:PORT
```

**Listener** (same `room` as host, e.g. `room1`)

```
http://LAN_IP:PORT/karaoke/listener-audience-local.html?api=http://LAN_IP:PORT&room=room1
```

The host page fills a **Listener URL** field when you change room or API; copy that to listeners.

---

## Optional: second static server

Only if you set `KARAOKE_SERVE_REPO_STATIC=0` or insist on serving HTML from another tool: run a separate static server and keep `?api=http://LAN_IP:8787` pointing at `local_audience_queue.py`. The default runbook path is **one process, one port**.

---

## Operator checklist (host)

1. Start **`local_audience_queue.py`** only; set `KARAOKE_LOCAL_HOST` / `KARAOKE_LOCAL_PUBLIC_BASE` if using phones on LAN.
2. Open host URL on **port PORT** (see above), with `?api=` matching that same base URL.
3. Set **Room ID** (share with listeners).
4. **Refresh songs** → pick a completed job.
5. Ensure lyrics exist for that job (`index-local.html` → save lyrics, or existing `lyrics/<job_id>.json`).
6. **Play** on host; listeners open listener URL and **Join** (or use `room=` in the URL).
7. If listeners don’t hear audio: confirm `KARAOKE_LOCAL_PUBLIC_BASE` uses **LAN_IP** (not `127.0.0.1`), firewall allows PORT, and avoid **https** pages calling **http** APIs (mixed content).

---

## Operator checklist (listener)

1. Same Wi‑Fi as host (unless you’ve routed ports and use WAN IP — not covered here).
2. Open listener URL with matching `api` and `room` (same **PORT** as host).
3. Tap **Join** (or rely on auto room from query).
4. Tap play on the audio control if the browser blocked autoplay.
5. For LRC, lines highlight from **local** `currentTime`; host publishes `position_sec` ~1s to reduce drift.

---

## API reference (audience)

**GET** `/api/audience/session?room_id=<id>`

- Returns `{ "found": true, "session": { ... } }` or `{ "found": false, "room_id": "..." }`.
- Session is in-memory only (lost on server restart).

**POST** `/api/audience/session`

- JSON body includes: `room_id`, `host_name`, `job_id`, `title`, `vocals_url`, `playing`, `position_sec`, `synced`, `lrc`, `text`.
- Host JS posts periodically while the page is open.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|----------------|--------|
| Listener never connects | Wrong API IP/port or firewall | Ping laptop; open `http://LAN_IP:PORT/api/list` on phone |
| Audio 404 or broken | `PUBLIC_BASE` still `127.0.0.1` | Set `KARAOKE_LOCAL_PUBLIC_BASE` to `http://LAN_IP:PORT` and refresh list / re-pick song |
| “Failed to fetch” from HTTPS page | Mixed content | Open pages over `http://` or use HTTPS everywhere + compatible API |
| Lyrics empty on listener | No saved lyrics for job | Save via `index-local.html` POST `/api/lyrics` |
| Host and listener out of sync | Polling interval + seek granularity | Normal for v1; optional future: offset slider / tighter sync |
| 404 for HTML | Static serving off | Set `KARAOKE_SERVE_REPO_STATIC=1` or use a separate static server |

---

## Security note

Audience session store has **no authentication**. Anyone on the network who guesses `room_id` can read/post session state. Use only on trusted LAN or add auth in a later revision.

---

## Related files

- `karaoke/local_audience_queue.py` — server entry (audience + full local queue)
- `karaoke/local_folder_queue.py` — core implementation (no audience routes); imported by `local_audience_queue.py`
- `karaoke/host-audience-local.html`, `karaoke/listener-audience-local.html`
- `assets/js/karaoke-audience-host-local.js`, `assets/js/karaoke-audience-listener-local.js`
