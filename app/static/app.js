// Video Discusser dashboard shell (Sprint 4).
//
// Rendering rule (docs/architecture.md §8): every dynamic value is written
// with textContent — model output, video URLs, and user input are untrusted
// and must never be parsed as HTML.
//
// Polling rule (roadmap Sprint 4): /api/status every ~2.5s; polling pauses
// while the tab is hidden and resumes with an immediate refresh. Failures
// show a disconnected banner and keep the last known state visibly stale
// instead of pretending it is current.
"use strict";

(function () {
  const POLL_INTERVAL_MS = 2500;
  const CHAT_HISTORY_LIMIT = 50;

  const els = {};
  [
    "conn-banner", "backend-version",
    "dot-backend", "dot-inference", "dot-media",
    "svc-backend", "svc-inference", "svc-media",
    "video-empty", "video-details",
    "video-id", "video-ts", "video-updated", "video-source", "video-revision",
    "chat-log", "chat-form", "question-input", "ask-button",
  ].forEach(function (id) {
    els[id] = document.getElementById(id);
  });

  let pollTimer = null;
  let pollInFlight = false;
  let lastKnownStatus = null; // body of the last successful /api/status
  let lastOkAt = null;        // Date of the last successful poll
  let chatStarted = false;    // has the user sent at least one question

  // --- helpers ---------------------------------------------------------------

  function setText(el, text) {
    if (el) el.textContent = text; // the only sanctioned write path
  }

  function setHidden(el, hidden) {
    if (el) el.classList.toggle("hidden", hidden);
  }

  function formatTimestamp(seconds) {
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const tenths = Math.floor((seconds - total) * 10);
    const mmss = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    return (h > 0 ? h + ":" : "") + mmss + "." + tenths;
  }

  function formatClock(date) {
    return date.toLocaleTimeString([], { hour12: false });
  }

  // --- rendering ---------------------------------------------------------------

  const DOT_CLASSES = ["dot-ok", "dot-unavailable", "dot-not_configured", "dot-unknown", "dot-pending"];

  function renderService(prefix, state) {
    const label = {
      ready: "ready",
      unavailable: "unavailable",
      not_configured: "not configured",
      unknown: "unknown",
    }[state] || state;
    setText(els["svc-" + prefix], label);
    if (els["dot-" + prefix]) {
      DOT_CLASSES.forEach(function (cls) {
        els["dot-" + prefix].classList.remove(cls);
      });
      els["dot-" + prefix].classList.add("dot-" + state);
    }
  }

  function renderServices(services) {
    renderService("backend", services.backend);
    renderService("inference", services.inference);
    renderService("media", services.media_tools);
  }

  function renderVideo(state) {
    if (!state) {
      setHidden(els["video-empty"], false);
      setHidden(els["video-details"], true);
      setChatEnabled(false);
      return;
    }
    setHidden(els["video-empty"], true);
    setHidden(els["video-details"], false);
    setText(els["video-id"], state.video_id);
    setText(els["video-ts"], formatTimestamp(state.timestamp_seconds) + " (" + state.timestamp_seconds + "s)");
    setText(els["video-updated"], formatClock(new Date(state.updated_at)));
    setText(els["video-source"], state.sync_source === "manual" ? "manual" : "pause event");
    setText(els["video-revision"], "#" + state.revision);
    setChatEnabled(true);
  }

  function renderStatus(body) {
    renderServices(body.services);
    renderVideo(body.active_video);
  }

  function renderOffline() {
    // Keep last known values on screen but mark them stale (roadmap Sprint 4:
    // never leave old status looking current).
    setHidden(els["conn-banner"], false);
    const when = lastOkAt ? formatClock(lastOkAt) : "never";
    setText(els["conn-banner"], "Disconnected from backend — showing last known state (last ok: " + when + ")");
    renderService("backend", "unavailable");
  }

  function renderOnline() {
    setHidden(els["conn-banner"], true);
  }

  function setChatEnabled(enabled) {
    if (!els["question-input"] || !els["ask-button"]) return;
    els["question-input"].disabled = !enabled;
    els["ask-button"].disabled = !enabled;
  }

  // --- chat shell (local only until the discussion sprint) ---------------------

  function appendChatMessage(kind, who, text) {
    if (!els["chat-log"]) return;
    if (chatStarted) {
      els["chat-log"].classList.remove("empty");
    }
    const msg = document.createElement("div");
    msg.className = "chat-msg" + (kind === "system" ? " system" : "");
    const whoSpan = document.createElement("span");
    whoSpan.className = "who";
    setText(whoSpan, who + ": ");
    const bodySpan = document.createElement("span");
    setText(bodySpan, text);
    msg.appendChild(whoSpan);
    msg.appendChild(bodySpan);
    els["chat-log"].appendChild(msg);
    while (els["chat-log"].children.length > CHAT_HISTORY_LIMIT) {
      els["chat-log"].removeChild(els["chat-log"].firstChild);
    }
    els["chat-log"].scrollTop = els["chat-log"].scrollHeight;
  }

  function onChatSubmit(event) {
    event.preventDefault();
    const question = els["question-input"].value.trim();
    if (!question) return;
    chatStarted = true;
    appendChatMessage("user", "You", question);
    els["question-input"].value = "";
    appendChatMessage(
      "system",
      "System",
      "Not sent — model discussion arrives in a later sprint. " +
        "The question is kept locally in this view only."
    );
  }

  // --- polling ------------------------------------------------------------------

  async function poll() {
    if (pollInFlight) {
      schedule();
      return;
    }
    pollInFlight = true;
    try {
      const resp = await fetch("/api/status", { headers: { Accept: "application/json" } });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      lastKnownStatus = await resp.json();
      lastOkAt = new Date();
      renderOnline();
      renderStatus(lastKnownStatus);
    } catch (err) {
      renderOffline(); // keep lastKnownStatus visible but stale
    } finally {
      pollInFlight = false;
    }
    schedule();
  }

  function schedule() {
    if (pollTimer) clearTimeout(pollTimer);
    if (document.hidden) return; // paused while the tab is hidden
    pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
  }

  async function loadVersionOnce() {
    try {
      const resp = await fetch("/api/health", { headers: { Accept: "application/json" } });
      if (!resp.ok) return;
      const body = await resp.json();
      setText(els["backend-version"], body.version);
    } catch (err) {
      setText(els["backend-version"], "—");
    }
  }

  function onVisibilityChange() {
    if (!document.hidden) poll(); // immediate refresh when returning
  }

  function init() {
    if (els["chat-form"]) els["chat-form"].addEventListener("submit", onChatSubmit);
    document.addEventListener("visibilitychange", onVisibilityChange);
    loadVersionOnce();
    poll();
  }

  init();
})();
