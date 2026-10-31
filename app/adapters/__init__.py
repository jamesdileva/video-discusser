"""Media source adapters. This is the only layer that knows how a video is
acquired (local file, YouTube download); everything downstream sees a plain
local `ResolvedMedia.path` that FFmpeg can read."""
