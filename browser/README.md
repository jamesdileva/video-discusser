# Browser sync — Tampermonkey userscript

`youtube-sync.user.js` sends the paused YouTube video's URL and timestamp to the
local Video Discusser backend. It runs entirely in your browser; the only network
target is your own machine (`127.0.0.1`).

## Install

1. Install [Tampermonkey](https://www.tampermonkey.net/) in your browser
   (Chrome/Edge/Firefox).
2. Open the Tampermonkey dashboard → **Utilities** → *Import from file*, or
   simply create a new script and paste the full contents of
   `browser/youtube-sync.user.js`.
3. On the first sync request, Tampermonkey asks to allow the cross-origin
   request to `http://127.0.0.1:8000`. Choose **Always allow** — this is the
   script's `@connect 127.0.0.1` grant.
4. Start the backend (`uvicorn app.main:app --host 127.0.0.1 --port 8000`),
   open the dashboard at <http://127.0.0.1:8000/>, open any YouTube
   **watch** page, and pause.

A small "Video Discusser" pill appears bottom-right on watch pages:

- `ready — pause to sync` — armed
- `synced 02:05.4` — the backend accepted the sync
- `already synced 02:05.4` — duplicate pause suppressed
- `syncing…` / `backend offline — try Sync now` — transport state
- `not a watch page — sync skipped` — URL without a video ID
- `ad break — not synced` — best-effort ad filter

The pill's **Sync now** button sends the current time manually
(`sync_source: "manual"`). Tampermonkey's extension menu also offers
**Sync now** and **Set backend origin** (loopback http(s) only).

## How it behaves

- Listens for `pause` in **capture mode** on `document`, so it survives YouTube
  replacing the video element during single-page navigation.
- Reads `location.href` and `video.currentTime` at event time — never cached.
- Suppresses duplicates: same video + timestamp within ±0.25 s is skipped.
- Requests use `GM_xmlhttpRequest`, so the backend needs **no CORS headers**
  and page scripts on youtube.com cannot reach it.
- Failures never break playback; they only update the pill.

## Manual test checklist (run on real YouTube with Tampermonkey)

Requires the backend running and the dashboard open.

- [ ] Pausing a video syncs the correct URL and timestamp (dashboard shows the
      video ID and `m:ss.t` matching the player).
- [ ] Play → pause again at a new position updates the dashboard.
- [ ] Navigating to a different video in the same tab (YouTube SPA) and
      pausing syncs the **new** video ID without a page refresh.
- [ ] Pausing near 0:00 is accepted (timestamp ≥ 0 is valid).
- [ ] Stopping the backend and pausing: the pill shows *backend offline*,
      playback is unaffected, and **Sync now** after restarting the backend
      succeeds.
- [ ] The pill does not appear on non-watch pages (homepage, channel pages).
- [ ] (Known limitation) pauses during ads may still sync; the ad filter is
      best-effort.

## Developer harness (no Tampermonkey needed)

With the backend running in development mode:

- <http://127.0.0.1:8000/dev-harness.html> — loads the real userscript with
  stubbed GM APIs, a fixture video, synthetic pause, simulated SPA navigation,
  and an activity log. Used by the sprint verification; also handy for
  quick regression checks after editing the userscript.

Fixtures: `fixtures/test-clip.mp4` (10 s generated test clip), served by the
dev-only routes `/dev/youtube-sync.user.js` and `/dev/test-clip.mp4`
(registered only when `APP_ENV=development`).
