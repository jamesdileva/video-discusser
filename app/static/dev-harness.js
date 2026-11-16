// Dev harness runtime (externalized so the CSP allows execution).
// Part 1: GM API stubs — MUST run before the userscript.

    "use strict";
    window.__gmStore = {};
    window.__gmCalls = [];
    window.GM_getValue = function (key, fallback) {
      return key in window.__gmStore ? window.__gmStore[key] : fallback;
    };
    window.GM_setValue = function (key, value) {
      window.__gmStore[key] = value;
    };
    window.GM_registerMenuCommand = function (label, fn) {
      window.__gmCalls.push({ kind: "menu", label: label });
      window.__gmMenuCommands = window.__gmMenuCommands || {};
      window.__gmMenuCommands[label] = fn;
      window.logLine && window.logLine("menu command registered: " + label);
    };
    window.GM_xmlhttpRequest = function (options) {
      window.__gmCalls.push({ kind: "request", url: options.url, data: options.data });
      window.logLine("GM_xmlhttpRequest → " + options.url);
      window.logLine("  payload: " + options.data);
      fetch(options.url, {
        method: options.method || "GET",
        headers: options.headers,
        body: options.data,
      })
        .then(async function (resp) {
          const text = await resp.text();
          window.logLine("  ← " + resp.status + " " + text.slice(0, 200));
          if (options.onload) options.onload({ status: resp.status, responseText: text });
        })
        .catch(function (err) {
          window.logLine("  ← network error: " + err);
          if (options.onerror) options.onerror(err);
        });
      return { abort: function () {} };
    };
  
// Part 2: harness logic.

    "use strict";
    (function () {
      const log = document.getElementById("log");
      window.logLine = function (line) {
        const stamp = new Date().toLocaleTimeString([], { hour12: false });
        log.textContent += "[" + stamp + "] " + line + "\n";
        log.scrollTop = log.scrollHeight;
      };

      const video = document.getElementById("fake-player");
      const seekInput = document.getElementById("seek-seconds");

      document.getElementById("btn-seek-pause").addEventListener("click", async function () {
        const target = Number(seekInput.value);
        try {
          if (video.readyState < 1) {
            await new Promise(function (resolve) { video.addEventListener("loadedmetadata", resolve, { once: true }); });
          }
          // Seek FIRST, then pause — so the natural pause event fires at the
          // target position, exactly like a real user pausing there.
          video.currentTime = target;
          if (!video.paused) {
            video.pause(); // natural pause event → the userscript should sync
          } else {
            window.logLine("already paused at " + target + "s (no new event; use the synthetic pause button)");
          }
        } catch (err) {
          window.logLine("seek/pause failed: " + err);
        }
      });

      document.getElementById("btn-synth-pause").addEventListener("click", function () {
        const target = Number(seekInput.value);
        if (Number.isFinite(target) && video.readyState >= 1) {
          try { video.currentTime = target; } catch (err) { /* ignore */ }
        }
        video.dispatchEvent(new Event("pause")); // capture-phase listener must catch this
        window.logLine("dispatched synthetic pause at currentTime=" + video.currentTime.toFixed(2) + "s");
      });

      document.getElementById("btn-spa").addEventListener("click", function () {
        const nextId = "aaaaaaaaaa" + Math.floor(Math.random() * 10); // exactly 11 chars
        window.__vdSimulatedHref = "https://www.youtube.com/watch?v=" + nextId + "&t=7s";
        document.dispatchEvent(new Event("yt-navigate-finish"));
        document.getElementById("current-path").textContent = window.__vdSimulatedHref;
        window.logLine("simulated SPA navigation → " + window.__vdSimulatedHref);
      });

      video.addEventListener("pause", function () {
        window.logLine("video 'pause' event at currentTime=" + video.currentTime.toFixed(2) + "s");
      });

      window.logLine("harness ready");

      // Simulated watch URL. On real YouTube the userscript reads
      // location.href; the harness can't change location to youtube.com, so
      // it provides the documented __vdTestHref seam instead. SPA navigation
      // is simulated by pointing it at a different video.
      window.__vdSimulatedHref = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1s";
      window.__vdTestHref = function () {
        return window.__vdSimulatedHref;
      };
      document.getElementById("current-path").textContent = window.__vdSimulatedHref;
      window.logLine("simulated watch URL: " + window.__vdSimulatedHref);
    })();
  
// Part 3: harness logic (was inline).
    "use strict";
    (function () {
      const log = document.getElementById("log");
      window.logLine = function (line) {
        const stamp = new Date().toLocaleTimeString([], { hour12: false });
        log.textContent += "[" + stamp + "] " + line + "\n";
        log.scrollTop = log.scrollHeight;
      };

      const video = document.getElementById("fake-player");
      const seekInput = document.getElementById("seek-seconds");

      document.getElementById("btn-seek-pause").addEventListener("click", async function () {
        const target = Number(seekInput.value);
        try {
          if (video.readyState < 1) {
            await new Promise(function (resolve) { video.addEventListener("loadedmetadata", resolve, { once: true }); });
          }
          // Seek FIRST, then pause — so the natural pause event fires at the
          // target position, exactly like a real user pausing there.
          video.currentTime = target;
          if (!video.paused) {
            video.pause(); // natural pause event → the userscript should sync
          } else {
            window.logLine("already paused at " + target + "s (no new event; use the synthetic pause button)");
          }
        } catch (err) {
          window.logLine("seek/pause failed: " + err);
        }
      });

      document.getElementById("btn-synth-pause").addEventListener("click", function () {
        const target = Number(seekInput.value);
        if (Number.isFinite(target) && video.readyState >= 1) {
          try { video.currentTime = target; } catch (err) { /* ignore */ }
        }
        video.dispatchEvent(new Event("pause")); // capture-phase listener must catch this
        window.logLine("dispatched synthetic pause at currentTime=" + video.currentTime.toFixed(2) + "s");
      });

      document.getElementById("btn-spa").addEventListener("click", function () {
        const nextId = "aaaaaaaaaa" + Math.floor(Math.random() * 10); // exactly 11 chars
        window.__vdSimulatedHref = "https://www.youtube.com/watch?v=" + nextId + "&t=7s";
        document.dispatchEvent(new Event("yt-navigate-finish"));
        document.getElementById("current-path").textContent = window.__vdSimulatedHref;
        window.logLine("simulated SPA navigation → " + window.__vdSimulatedHref);
      });

      video.addEventListener("pause", function () {
        window.logLine("video 'pause' event at currentTime=" + video.currentTime.toFixed(2) + "s");
      });

      window.logLine("harness ready");

      // Simulated watch URL. On real YouTube the userscript reads
      // location.href; the harness can't change location to youtube.com, so
      // it provides the documented __vdTestHref seam instead. SPA navigation
      // is simulated by pointing it at a different video.
      window.__vdSimulatedHref = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1s";
      window.__vdTestHref = function () {
        return window.__vdSimulatedHref;
      };
      document.getElementById("current-path").textContent = window.__vdSimulatedHref;
      window.logLine("simulated watch URL: " + window.__vdSimulatedHref);
    })();