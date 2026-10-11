# ADR 0002 — Every external capability sits behind a provider protocol + router

* Status: accepted
* Date: 2026-10-10
* Context: system plan §3, §10.3, §10.4, §18 (risk: "free-tier limits change or vanish")

## Context

The product depends on four external capabilities (LLM, STT, TTS, pronunciation
assessment) delivered by vendors whose free tiers are explicitly described in the
plan as snapshots that change often. A vendor changing its free tier must be a
config change, not a rewrite.

## Decision

* Four `Protocol`s in `providers/base.py`: `LLMProvider`, `STTProvider`,
  `TTSProvider`, `PronunciationProvider`. Adapters implement only these.
* Groq, xAI, Gemini and Ollama are all OpenAI-compatible, so they share one
  adapter parameterised by `base_url`/`key`/`model`. Model names are **never**
  hard-coded — they come from env.
* A `ProviderRouter` owns ordering, health and failover: per-provider token
  buckets mirroring vendor limits (so we queue instead of 429-ing), a circuit
  breaker that trips on `429`/`5xx` and honours `Retry-After`, and a
  `usage_ledger` write for every call.
* **Every chain ends in a provider that cannot fail**: `MockLLM`, `MockSTT`,
  `MockTTS`, `HeuristicPronunciation`. Consequence: the app boots and the whole
  core loop works with an empty `.env`, which is also how the test suite runs.
* `TS_PROVIDER_MODE=auto` (default) selects a live adapter when its key is
  present and the mock otherwise; `mock` forces offline; `live` refuses to start
  without a real provider, for production.
* TTS routing is **per language**, because the capability matrix is not uniform:
  Deepgram Aura-2 has no Korean (plan §3.3), so `TTS_ROUTE_KO` omits it.

## Consequences

* Swapping or adding a vendor is an env edit plus, at most, one adapter file.
* Degradation is ordered and visible (`provider_trace` on the session, banner in
  the UI) rather than a hard failure — plan §14.3, "never block a session
  mid-conversation; degrade instead".
* Cost: an extra indirection on every call, and mock output is obviously not
  production quality — a developer must check `GET /v1/admin/providers/health`
  to know which tier they are really on.
