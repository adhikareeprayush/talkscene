# ADR 0003 — Pronunciation is scored on two tracks, and estimates are labelled

* Status: accepted
* Date: 2026-10-10
* Context: system plan §3.4, §8.5 ("the honest, workable design")

## Context

Whisper-family models are language-model-biased: they quietly repair a learner's
mispronounced or ungrammatical utterance into the correct sentence. A transcript
therefore flatters the learner, and using it to score pronunciation would teach
the wrong thing. Azure Pronunciation Assessment does score phonemes, but the free
F0 tier allows only 5 audio hours per month.

## Decision

Two tracks, never mixed in the UI:

1. **Passive, during conversation.** Per-word Whisper confidence
   (`avg_logprob` → probability), word timings and `no_speech_prob` produce
   *unclear word candidates*. These are surfaced as
   `confidence: "estimated"` and the UI must render the word "estimated".
   No score is computed from them.
2. **Active, after conversation — shadowing drills.** 3–5 short sentences built
   from the flagged words are sent to Azure PA in *scripted* mode with a known
   reference text, which is its most reliable configuration. This returns
   accuracy / fluency / completeness / prosody plus per-word and per-phoneme
   detail, and it spends the scarce free hours only on short, high-value clips.

Fluency metrics (WPM, pause distribution, response latency, fillers) are
computed from word timestamps in our own code — `engine/fluency.py` — not asked
of an LLM, because they are arithmetic and an LLM would hallucinate them.

Azure PA is reached over the short-audio REST endpoint with the
`Pronunciation-Assessment` header rather than the Speech SDK, to avoid a
~100 MB native dependency in the API image.

## Consequences

* The learner is never shown a precise-looking pronunciation number derived from
  a source that cannot support it.
* Drill audio must be 16 kHz mono PCM WAV for the REST endpoint, so the client
  uploads WebM/Opus and the server transcodes (ffmpeg, optional dependency —
  without it the heuristic provider is used and says so).
* `QUOTA_DRILL_SECONDS_PER_MONTH` guards the 5-hour Azure allowance.
