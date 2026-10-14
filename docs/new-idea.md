# New Idea: General-Purpose Video Summarizer and Discussion Companion

**Status:** Proposed addition to the existing Video Discusser & Legal Commentary Agent project  
**Document type:** Additive feature proposal  
**Scope:** Capture the new idea without rewriting `architecture.md`, `sprint-roadmap.md`, or `implementation-guide.md`.

## 1. The Idea

Expand the project from a tool for asking questions about a paused video moment into a **general-purpose local video companion** that can also explain an entire video after the user finishes watching it.

The user should be able to watch a video normally, pause at a confusing or important moment and ask a question, or finish watching and ask:

- “What was this video about?”
- “Can you summarize the whole thing?”
- “What were the main points?”
- “Give me a chronological breakdown.”
- “What claims did the speaker make, and what evidence was shown?”
- “What happened immediately before and after this moment?”
- “Explain this crash/bodycam clip in order, separating what is visible from what you infer.”

The product should be **general-purpose first**, not a tool optimized only for legal analysis or bodycam footage. Tutorials, lectures, documentaries, reviews, news/commentary, gameplay, interviews, incident videos, crash footage, and bodycam videos should all be valid use cases. Some videos will work better than others depending on visual clarity, available captions/transcripts, length, and model limitations.

Bodycam, crash, and other incident footage remain useful examples of the tool's value, but they are use cases rather than the product's defining identity.

## 2. Two Complementary Modes

### A. Live Discussion Mode

Preserve the existing core interaction:

1. The user watches a video in a supported browser.
2. The user pauses at a moment and asks a question.
3. The browser helper sends the video URL and timestamp to the local backend.
4. The backend obtains a small surrounding time window, extracts a bounded set of frames, and optionally obtains nearby transcript text.
5. The local vision-language model answers with reference to the supplied evidence.

Example questions:

- “What is happening here?”
- “What changed between these two moments?”
- “What does the sign on the wall say?”
- “What happened just before this?”
- “Is that object clearly visible, or is the video too blurry to tell?”

This mode should prioritize responsiveness and a small time window rather than processing the entire video.

### B. Whole-Video Summary Mode

Add a way to request a summary of the current video after watching it, or to submit a supported video URL or local video file for summarization.

The user should be able to choose a summary style:

- **Quick overview:** A short description of the video's subject and conclusion.
- **Standard summary:** The main ideas or events, in order.
- **Detailed timeline:** A timestamped sequence of important segments.
- **Key takeaways:** Important lessons, conclusions, or practical points.
- **Claims and evidence:** A structured list of claims and the transcript or visual material that appears to support them.
- **Explain this video:** A conversational overview followed by suggested questions.

The initial release does not need a complex menu of modes. A practical MVP is **Quick overview**, **Standard summary**, and **Timestamped timeline**, with claims/evidence as a later refinement.

Whole-video mode is a batch workflow. It can take longer than live discussion and should report progress rather than pretending the entire video is processed instantly.

## 3. How Whole-Video Summarization Should Work

Do not try to send every frame of a long video to a single model request. That would be expensive in processing time and memory, particularly on the target machine with approximately 4 GB of VRAM.

Use a bounded, multi-stage pipeline instead:

1. **Resolve the input.** Identify the video, its duration, and available metadata. Support the currently planned source first; add local-file input if it fits the implementation.
2. **Acquire transcript text when available.** Prefer usable captions or a supplied transcript. Transcript availability varies by source and video. If no transcript is available, continue with visual analysis and clearly communicate that spoken content may be missed.
3. **Divide the video into time segments.** Use configurable segment sizes and overlap where helpful so important transitions near boundaries are not lost.
4. **Create a visual sample for each segment.** Extract a small, controlled number of representative frames. Avoid unbounded extraction or loading all frames into memory.
5. **Analyze each segment.** Use transcript text to understand speech and narration, and sampled frames to understand visible actions, objects, scenes, on-screen text, and changes. Keep the evidence associated with timestamps.
6. **Build segment notes.** Store concise notes for each time range, including important events or ideas, timestamps, evidence source, and uncertainty.
7. **Combine the segment notes.** Generate the requested overall summary from the segment notes instead of resending the full video to the model.
8. **Present the result.** Show the summary, timestamps, key points, and any limitations. Where feasible, let the user click a timestamp to return to that part of the video.
9. **Allow follow-up questions.** Keep the summary and its segment notes available to the active session so the user can ask follow-up questions without restarting the entire process.

This is a map-and-combine workflow: summarize manageable pieces first, then synthesize those summaries into the whole-video result.

### Evidence sources should remain distinct

A segment's evidence can include:

- **Transcript evidence:** What captions or transcript text say.
- **Visual evidence:** What is visible in sampled frames.
- **Model interpretation:** A conclusion inferred from the supplied evidence.
- **Unknown / unclear:** Details the available evidence cannot establish.

The UI and prompts should avoid presenting a model inference as if it were directly observed. A sampled frame may miss an action that occurred between frames, and a transcript may omit visual context. The summary should be allowed to say that something cannot be determined.

## 4. Transcript and Visual Analysis Should Complement Each Other

Frames alone are not enough for a reliable general-purpose summarizer. A frame sampler can show that a lecturer is at a whiteboard, but it may miss the explanation being spoken. Conversely, a transcript can explain a tutorial while missing a visual demonstration, an on-screen warning, or a significant event.

The design should therefore use a **transcript-plus-visual approach when both sources are available**:

- Transcript text is the primary source for narration, dialogue, and spoken explanations.
- Sampled frames help describe what is visible and identify important visual changes.
- Timestamps link the two sources.
- The final summary combines both, while noting when one source is unavailable.

Implementation should be incremental:

1. Start with captions/transcripts available through the supported source, where permitted and technically reliable.
2. Support a user-provided transcript if practical.
3. Consider optional local speech-to-text later for videos without captions. Treat this as an additional capability with its own runtime, accuracy, performance, and setup requirements, not as a prerequisite for the first MVP.

The tool should not claim to have understood all spoken content when it only analyzed frames.

## 5. Performance and Hardware Constraints

The existing project targets a Windows PC with roughly 4 GB of VRAM and 16 GB of RAM. The summarizer must be designed around those constraints.

Requirements:

- Keep frame counts per segment configurable and capped.
- Process small batches sequentially instead of retaining all video frames in memory.
- Use transcript text to reduce unnecessary visual sampling when speech carries most of the meaning.
- Make visual sampling denser around important changes only if the architecture later supports detecting those changes reliably.
- Cache intermediate results for the current job so a summary can be retried or reformatted without repeating every expensive step.
- Clean up temporary media and intermediate files according to a documented retention policy.
- Show job progress, elapsed time where available, and actionable failure messages.
- Allow cancellation of a long-running summary.
- Never promise a fixed processing speed before testing the chosen model and runtime on the actual hardware.

A short video with clear captions may summarize quickly. A long video with no transcript and many scene changes may be slower and less complete. That difference should be visible in the UX rather than hidden.

## 6. User Experience

Keep the interface simple and consistent with the existing dashboard.

A possible flow:

1. Open or synchronize a supported video.
2. Choose **Discuss a moment** or **Summarize video**.
3. For a summary, choose a detail level and start processing.
4. View progress and any transcript/source availability status.
5. Read the summary and timestamped timeline.
6. Ask a follow-up question, or jump to a relevant timestamp.

The summary view should make these details clear:

- Video title or URL and duration, when available.
- Whether transcript text was available and used.
- Whether the summary is based primarily on sampled frames.
- Processing status and any limitations.
- Timestamps that link summary statements to relevant sections when supported.
- A way to retry a failed stage without silently discarding completed work.

Avoid a separate, overcomplicated application experience for each video category. The same workflow should work for a lecture, a documentary, a bodycam video, or crash footage.

## 7. MVP Scope

### Include in the initial summarizer MVP

- A user-triggered whole-video summary for the supported video source.
- Quick overview and standard summary output.
- A timestamped, chronological breakdown.
- Bounded frame extraction and sequential segment processing.
- Transcript use when reliably and permissibly available.
- Clear indication when transcript content is unavailable.
- Progress, cancellation, and readable error states.
- Follow-up questions based on the produced summary and segment notes, subject to the existing discussion architecture.
- Temporary-file cleanup and sensible resource limits.

### Defer until the core works reliably

- Automatic local speech-to-text for every unsupported video.
- Highly granular event detection or guaranteed coverage of every action.
- Automatic fact-checking against the open web.
- Formal legal conclusions or definitive identification of people, intent, fault, or criminal conduct.
- Batch summarization of playlists or channels.
- Cloud processing or mandatory accounts.
- Complex editing/export workflows and permanent video-library management.

## 8. Evaluation and Quality Checks

Do not evaluate the summarizer only by whether its output sounds fluent. It should be checked for coverage, chronology, evidence grounding, and honesty about uncertainty.

Build a small test set covering varied content:

- A short tutorial with clear speech and visible steps.
- A lecture or interview where speech carries most of the information.
- A documentary or commentary video with multiple topics.
- A video with little or no speech.
- A video with rapid visual changes.
- A bodycam or crash video where event order matters.
- A video with unavailable captions or a deliberately supplied transcript.

For each test video, manually record the main points and important timestamps. Verify:

- Does the summary capture the central subject and major points?
- Are events in the correct order?
- Are timestamps close enough to be useful?
- Does it distinguish transcript statements from visible evidence?
- Does it invent actions, dialogue, identities, or conclusions not supported by the input?
- Does it disclose missing transcript coverage?
- Can the target hardware complete the job without excessive memory use or an uncontrolled backlog?
- Can a failed segment be retried without restarting the entire video unnecessarily?

Use a repeatable test set and record latency, failures, peak memory where practical, and human-rated quality before increasing frame counts or model size.

## 9. Reliability, Privacy, and Source Constraints

The feature should retain the existing project's local-first direction wherever practical.

- Keep inference and dashboard services local unless an explicit external service is configured.
- Treat video URLs, captions, transcripts, filenames, and extracted text as untrusted input.
- Do not assume every video source allows downloading or caption extraction. Use permitted access methods and explain unsupported cases.
- Prefer clear errors over bypassing access controls or attempting to evade source restrictions.
- Do not retain full video files or extracted frames longer than needed unless the user explicitly enables history.
- Avoid writing sensitive video content or full transcripts into routine logs.
- Keep legal and incident analysis descriptive and evidence-linked. The application can help users understand footage, but it should not present itself as a lawyer, investigator, or authoritative judge of fault.

## 10. Integration with the Existing Architecture Suite

This file is an **additive idea note**, not a replacement for the existing documents.

The current architecture suite remains the source of truth for the existing live-discussion implementation. If this idea is approved for implementation, update the suite only when the relevant work is scheduled:

- **`architecture.md`:** Add a summarization job/workflow, segment result structure, transcript adapter, job status/progress/cancellation, and summary endpoints.
- **`sprint-roadmap.md`:** Add an early feasibility/test sprint, then schedule a minimal summary pipeline after media acquisition, frame extraction, and inference have working tests. Keep transcript improvements and advanced features in later sprints.
- **`implementation-guide.md`:** Add setup, debugging, and verification steps for transcript acquisition and whole-video jobs only when those features are ready to implement.

Avoid duplicating the whole architecture in this note. Keep this document as the feature proposal and acceptance criteria.

## 11. Recommended Implementation Order

1. **Prove the media path:** Confirm that the existing environment can identify a video, obtain duration, and extract a small set of timestamped frames.
2. **Prove transcript access:** Test availability, timestamp alignment, missing captions, and clear failure behavior for the supported source.
3. **Build segment records:** Define a small internal structure for time range, transcript excerpt, frame references, notes, and errors.
4. **Summarize one segment:** Verify that the local model can produce grounded notes for one segment within hardware limits.
5. **Summarize a short whole video:** Process segments sequentially and combine their notes into a coherent chronological summary.
6. **Expose a simple UI:** Add summary request, progress, cancel/retry, and results.
7. **Evaluate varied videos:** Run the test set and record quality and performance before expanding the scope.
8. **Add follow-up context:** Let the user ask questions against the generated summary and segment evidence.
9. **Improve incrementally:** Add local speech-to-text, smarter frame selection, exports, or history only when the core pipeline demonstrates value.

## 12. Definition of Done for the First Version

The first version is ready when a user can submit a supported video, receive a readable overview and timestamped chronological summary, understand whether transcript text was used, and ask a relevant follow-up question. It must handle missing captions, extraction failures, cancellation, and individual segment errors without crashing or silently fabricating a complete result.

The summary does not need to describe every frame. It does need to accurately represent the video's major points, preserve event order, cite useful timestamps where available, and be transparent about what it could not determine.
