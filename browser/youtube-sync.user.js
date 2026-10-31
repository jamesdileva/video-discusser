// ==UserScript==
// @name         Video Discusser — YouTube pause sync
// @namespace    video-discusser
// @version      0.1.0
// @description  Sends the paused YouTube video URL and timestamp to the local Video Discusser backend (127.0.0.1 only).
// @match        https://www.youtube.com/watch*
// @match        https://m.youtube.com/watch*
// @match        https://youtube.com/watch*
// @run-at       document-idle
// @noframes
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

/*
 * Pause-to-sync for Video Discusser (docs/architecture.md §8, workflow A).
 *
 * Design notes:
 * - The `pause` listener is attached to `document` in CAPTURE mode: media
 *   events do not bubble, but capture-phase ancestors still observe them.
 *   This survives YouTube replacing the <video> element during SPA
 *   navigation — no rebinding is ever needed.
 * - `location.href` and `video.currentTime` are read at event time, never
 *   cached; YouTube changes videos without a page load.
 * - Transport is GM_xmlhttpRequest so the backend stays loopback-strict with
 *   no CORS headers at all (page scripts on youtube.com cannot reach it).
 * - Duplicate suppression: identical video + timestamp within a small
 *   epsilon is skipped, so player-internal double pauses do not spam state.
 * - Everything is failure-isolated: a backend error must never break
 *   playback; it only updates the badge.
 */

(function () {
  "use strict";

  /**
   * Pure, DOM-free sync logic. Exported for the Node smoke tests in
   * tests/js/ and shared verbatim by the dev harness.
   */
  function coreFactory() {
    const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;
    // Must mirror app/services/youtube_url.py exactly.
    const ALLOWED_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]);

    function extractVideoId(href) {
      try {
        const url = new URL(href);
        if (url.protocol !== "https:" && url.protocol !== "http:") return null;
        const host = (url.hostname || "").toLowerCase().replace(/\.$/, "");
        if (!ALLOWED_HOSTS.has(host)) return null;
        if (host === "youtu.be") {
          const id = url.pathname.slice(1).split("/")[0];
          return VIDEO_ID_RE.test(id) ? id : null;
        }
        if (url.pathname.replace(/\/+$/, "") === "/watch") {
          const values = url.searchParams.getAll("v");
          // Exactly one `v`, like the backend — duplicates are rejected, not guessed.
          if (values.length !== 1) return null;
          return VIDEO_ID_RE.test(values[0]) ? values[0] : null;
        }
        if (url.pathname.startsWith("/shorts/")) {
          const id = url.pathname.slice("/shorts/".length).split("/")[0];
          return VIDEO_ID_RE.test(id) ? id : null;
        }
        return null;
      } catch (err) {
        return null;
      }
    }

    function buildPayload(href, timestampSeconds, syncSource) {
      return {
        url: href,
        timestamp_seconds: Number(timestampSeconds),
        video_id: extractVideoId(href), // may be null; the backend re-derives
        sync_source: syncSource, // "pause_event" | "manual"
      };
    }

    function isDuplicate(last, candidate, epsilonSeconds) {
      if (!last) return false;
      if (last.url !== candidate.url) return false;
      if (last.sync_source !== candidate.sync_source) return false;
      if (!Number.isFinite(candidate.timestamp_seconds)) return false;
      return Math.abs(last.timestamp_seconds - candidate.timestamp_seconds) <= epsilonSeconds;
    }

    function formatTimestamp(seconds) {
      // Format from the decimal string — see the dashboard twin of this
      // function for why (floating-point tenths flooring bug).
      if (!Number.isFinite(seconds) || seconds < 0) return "?";
      const fixed = seconds.toFixed(1);
      const total = Math.floor(Number(fixed));
      const tenths = fixed.split(".")[1] || "0";
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const mmss = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
      return (h > 0 ? h + ":" : "") + mmss + "." + tenths;
    }

    return {
      VIDEO_ID_RE,
      ALLOWED_HOSTS,
      extractVideoId,
      buildPayload,
      isDuplicate,
      formatTimestamp,
    };
  }

  const core = coreFactory();

  // Node/test export (module is undefined in the Tampermonkey sandbox).
  if (typeof module !== "undefined" && module.exports !== undefined) {
    module.exports = core;
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    return; // not a browser context (tests)
  }
  main(core);

  function main(coreRef) {
    const DEDUPE_EPSILON_SECONDS = 0.25;
    const REQUEST_TIMEOUT_MS = 5000;

    const LOOPBACK_ORIGIN_RE = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/;
    const BACKEND_ORIGIN = loadOrigin();

    let lastAccepted = null; // last payload the backend accepted (200)

    // --- configuration -------------------------------------------------------

    function loadOrigin() {
      try {
        if (typeof GM_getValue === "function") {
          const stored = GM_getValue("backendOrigin", "");
          if (stored && LOOPBACK_ORIGIN_RE.test(stored)) return stored;
        }
      } catch (err) {
        /* fall through to default */
      }
      return "http://127.0.0.1:8000";
    }

    function registerMenu() {
      if (typeof GM_registerMenuCommand !== "function") return;
      GM_registerMenuCommand("Video Discusser: Sync now", function () {
        attemptSync("manual");
      });
      GM_registerMenuCommand("Video Discusser: Set backend origin", function () {
        const next = window.prompt("Backend origin (loopback http(s) only):", BACKEND_ORIGIN);
        if (next === null) return;
        const trimmed = next.trim();
        if (!LOOPBACK_ORIGIN_RE.test(trimmed)) {
          window.alert("Rejected: only loopback http(s) origins are allowed.");
          return;
        }
        GM_setValue("backendOrigin", trimmed);
        window.location.reload();
      });
    }

    // --- badge ---------------------------------------------------------------

    let badge = null;
    let badgeText = null;
    let badgeButton = null;

    function ensureBadge() {
      if (badge) return;
      const host = document.body || document.documentElement;
      if (!host) return; // page not ready yet; next call retries
      badge = document.createElement("div");
      badge.id = "vd-sync-badge";
      badge.setAttribute("aria-live", "polite");
      badge.style.cssText =
        "position:fixed;right:12px;bottom:12px;z-index:2147483647;display:flex;" +
        "align-items:center;gap:6px;padding:4px 8px;border-radius:999px;" +
        "background:rgba(20,22,28,0.85);color:#e6e8ee;font:12px 'Segoe UI',sans-serif;" +
        "border:1px solid rgba(255,255,255,0.18);box-shadow:0 2px 8px rgba(0,0,0,0.35);";
      badgeText = document.createElement("span");
      setText(badgeText, "Video Discusser: starting…");
      badgeButton = document.createElement("button");
      setText(badgeButton, "Sync now");
      badgeButton.title = "Send the current video time to the Video Discusser backend";
      badgeButton.style.cssText =
        "border:none;border-radius:999px;background:#7aa2f7;color:#10131c;" +
        "font:600 11px 'Segoe UI',sans-serif;padding:2px 8px;cursor:pointer;";
      badgeButton.addEventListener("click", function () {
        attemptSync("manual");
      });
      badge.appendChild(badgeText);
      badge.appendChild(badgeButton);
      host.appendChild(badge);
      setBadge("ready — pause to sync", "idle");
    }

    // textContent-only rendering: badge text comes from this script and from
    // backend error codes, never parsed as HTML.
    function setBadge(text, kind) {
      ensureBadge();
      if (!badge || !badgeText) return;
      const colors = {
        ok: "rgba(76,195,138,0.9)",
        error: "rgba(229,72,77,0.9)",
        pending: "rgba(212,167,44,0.9)",
        idle: "rgba(255,255,255,0.25)",
      };
      setText(badgeText, "Video Discusser: " + text);
      badge.style.borderColor = colors[kind] || colors.idle;
    }

    function setText(el, text) {
      if (el) el.textContent = text;
    }

    // --- transport ------------------------------------------------------------

    function sendToBackend(payload) {
      const body = JSON.stringify(payload);
      const finish = function (ok, statusOrError, detail) {
        if (ok && statusOrError === 200) {
          lastAccepted = payload;
          setBadge("synced " + coreRef.formatTimestamp(payload.timestamp_seconds), "ok");
          return;
        }
        if (ok) {
          // Structured backend rejection (4xx): surface the stable code.
          let code = "HTTP " + statusOrError;
          try {
            const parsed = JSON.parse(detail || "{}");
            if (parsed.error && parsed.error.code) code = parsed.error.code;
          } catch (err) {
            /* keep HTTP status as the code */
          }
          setBadge("rejected (" + code + ")", "error");
          return;
        }
        setBadge("backend offline — try Sync now", "error");
      };

      if (typeof GM_xmlhttpRequest === "function") {
        GM_xmlhttpRequest({
          method: "POST",
          url: BACKEND_ORIGIN + "/api/sync",
          headers: { "Content-Type": "application/json" },
          data: body,
          timeout: REQUEST_TIMEOUT_MS,
          onload: function (response) {
            finish(true, response.status, response.responseText);
          },
          onerror: function () {
            finish(false, "error");
          },
          ontimeout: function () {
            finish(false, "timeout");
          },
        });
        return;
      }

      // Degraded path (no GM API — e.g. the dev harness without stubs).
      // Cross-origin from youtube.com this will fail CORS by design; on the
      // same-origin dev harness it works.
      window
        .fetch(BACKEND_ORIGIN + "/api/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body,
        })
        .then(async function (resp) {
          finish(true, resp.status, await resp.text());
        })
        .catch(function () {
          finish(false, "error");
        });
    }

    // --- sync attempt -----------------------------------------------------------

    function findMainVideo() {
      const main = document.querySelector("video.html5-main-video");
      if (main) return main;
      return document.querySelector("video");
    }

    function isSyncTarget(element) {
      // Only the main player video (or, outside YouTube, the only video).
      const main = document.querySelector("video.html5-main-video");
      if (main) return element === main;
      return true;
    }

    function attemptSync(syncSource) {
      try {
        // location.href is always fresh — YouTube is a SPA. __vdTestHref is a
        // harness-only seam (undefined in production); a page could spoof the
        // reported URL with it, but the page already controls its own video
        // element, so this grants no new capability.
        const href =
          typeof window.__vdTestHref === "function"
            ? window.__vdTestHref()
            : window.location.href;
        const video = findMainVideo();
        if (!video) {
          setBadge("no video found", "error");
          return;
        }
        if (document.querySelector("#movie_player.ad-showing")) {
          // Best-effort ad filter; if YouTube changes its DOM this simply
          // stops filtering and ads sync like any other moment.
          setBadge("ad break — not synced", "idle");
          return;
        }
        const payload = coreRef.buildPayload(href, video.currentTime, syncSource);
        if (!payload.video_id) {
          setBadge("not a watch page — sync skipped", "idle");
          return;
        }
        if (coreRef.isDuplicate(lastAccepted, payload, DEDUPE_EPSILON_SECONDS)) {
          setBadge("already synced " + coreRef.formatTimestamp(payload.timestamp_seconds), "idle");
          return;
        }
        setBadge("syncing…", "pending");
        sendToBackend(payload);
      } catch (err) {
        setBadge("sync failed (script error)", "error");
      }
    }

    // --- listeners ---------------------------------------------------------------

    document.addEventListener(
      "pause",
      function (event) {
        const target = event.target;
        if (target && target.tagName === "VIDEO" && isSyncTarget(target)) {
          attemptSync("pause_event");
        }
      },
      true
    );

    document.addEventListener(
      "yt-navigate-finish",
      function () {
        setBadge("ready — pause to sync", "idle");
      },
      true
    );

    registerMenu();
    ensureBadge();
  }
})();
