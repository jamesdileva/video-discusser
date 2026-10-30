// Sprint 2 shell: verify the backend is reachable and show its version.
// All dynamic content is rendered with textContent (never innerHTML) —
// model output and video metadata are untrusted (docs/architecture.md §8).
"use strict";

(function () {
  const statusEl = document.getElementById("backend-status");
  const versionEl = document.getElementById("backend-version");

  function render(state, text, version) {
    statusEl.textContent = text;
    statusEl.className = "state state-" + state;
    versionEl.textContent = version ? "version " + version : "";
  }

  async function checkHealth() {
    try {
      const resp = await fetch("/api/health", { headers: { Accept: "application/json" } });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const body = await resp.json();
      render("ok", "Connected", body.version);
    } catch {
      render("bad", "Disconnected", "");
    }
  }

  checkHealth();
  setInterval(checkHealth, 5000);
})();
