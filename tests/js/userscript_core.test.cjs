// Node smoke tests for the userscript's DOM-free core. Run via
// `node tests/js/userscript_core.test.cjs`; pytest invokes this when node is
// available (tests/test_userscript.py). Mirrors the backend URL contract in
// tests/test_youtube_url.py so client and server can never drift apart.

"use strict";

const assert = require("node:assert");
const core = require("../../browser/youtube-sync.user.js");

// --- extractVideoId: accepted forms ------------------------------------------

const accepted = [
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s&list=PL123", "dQw4w9WgXcQ"],
  ["https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
  ["https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
  ["https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"],
  ["https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"],
];

for (const [url, expected] of accepted) {
  assert.strictEqual(core.extractVideoId(url), expected, `extractVideoId(${url})`);
}

// --- extractVideoId: rejected forms ------------------------------------------

const rejected = [
  "https://evil.com/watch?v=dQw4w9WgXcQ",
  "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
  "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
  "https://music.youtube.com/watch?v=dQw4w9WgXcQ", // not on the backend allowlist either
  "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "javascript:alert(1)",
  "https://www.youtube.com/embed/dQw4w9WgXcQ",
  "https://www.youtube.com/playlist?list=PL123",
  "https://www.youtube.com/",
  "https://www.youtube.com/watch?t=10",
  "https://www.youtube.com/watch?v=short",
  "https://www.youtube.com/watch?v=",
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=abc12345678", // duplicate v
  "https://youtu.be/",
  "https://youtu.be//dQw4w9WgXcQ",
  "not a url at all",
];

for (const url of rejected) {
  assert.strictEqual(core.extractVideoId(url), null, `extractVideoId(${url}) must reject`);
}

// --- buildPayload --------------------------------------------------------------

{
  const payload = core.buildPayload("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 125.4, "pause_event");
  assert.deepStrictEqual(
    Object.keys(payload).sort(),
    ["sync_source", "timestamp_seconds", "url", "video_id"],
    "payload keys must match the backend SyncPayload contract"
  );
  assert.strictEqual(payload.video_id, "dQw4w9WgXcQ");
  assert.strictEqual(payload.timestamp_seconds, 125.4);
  assert.strictEqual(payload.sync_source, "pause_event");
}

{
  const payload = core.buildPayload("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 7, "manual");
  assert.strictEqual(payload.sync_source, "manual");
}

// --- isDuplicate ------------------------------------------------------------------

const base = { url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ", timestamp_seconds: 100, sync_source: "pause_event" };

assert.strictEqual(core.isDuplicate(null, base, 0.25), false, "nothing before first sync");
assert.strictEqual(core.isDuplicate(base, { ...base, timestamp_seconds: 100.1 }, 0.25), true, "same spot within epsilon");
assert.strictEqual(core.isDuplicate(base, { ...base, timestamp_seconds: 100.25 }, 0.25), true, "exact epsilon boundary dedupes");
assert.strictEqual(core.isDuplicate(base, { ...base, timestamp_seconds: 100.3 }, 0.25), false, "beyond epsilon sends");
const manual = { ...base, sync_source: "manual" };
assert.strictEqual(core.isDuplicate(base, manual, 0.25), false, "manual always distinct from pause");
assert.strictEqual(
  core.isDuplicate(base, { ...base, url: "https://www.youtube.com/watch?v=abc12345678" }, 0.25),
  false,
  "different video sends"
);
assert.strictEqual(
  core.isDuplicate(base, { ...base, timestamp_seconds: NaN }, 0.25),
  false,
  "non-finite candidate never dedupes silently"
);

// --- formatTimestamp -----------------------------------------------------------------

assert.strictEqual(core.formatTimestamp(125.4), "02:05.4");
assert.strictEqual(core.formatTimestamp(3725.55), "1:02:05.5");
assert.strictEqual(core.formatTimestamp(0), "00:00.0");
assert.strictEqual(core.formatTimestamp(-1), "?");
assert.strictEqual(core.formatTimestamp(NaN), "?");

console.log("userscript core: all assertions passed");
