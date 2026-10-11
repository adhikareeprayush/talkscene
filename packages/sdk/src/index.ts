/**
 * The TalkScene client.
 *
 * Types come from `schema.d.ts`, which is generated from `docs/openapi.yaml`.
 * The hand-written parts are the three things the contract cannot express on
 * its own: token refresh, the SSE turn stream, and multipart audio uploads.
 */

import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";
import { readEventStream, SseError, type SseMessage } from "./sse";
import {
  browserTokenStore,
  isExpired,
  store,
  type StoredSession,
  type TokenPair,
  type TokenStore,
} from "./tokens";

export * from "./tokens";
export { readEventStream, SseError, type SseMessage } from "./sse";
export type { components, paths } from "./schema";

type S = components["schemas"];

export type Problem = S["Problem"];
export type Me = S["Me"];
export type MeUpdate = S["MeUpdate"];
export type LanguageInfo = S["LanguageInfo"];
export type ScenarioCard = S["ScenarioCard"];
export type ScenarioBrief = S["ScenarioBrief"];
export type SessionState = S["SessionState"];
export type SessionDetail = S["SessionDetail"];
export type SessionSummary = S["SessionSummary"];
export type StartSessionResponse = S["StartSessionResponse"];
export type TurnOut = S["TurnOut"];
export type GoalState = S["GoalState"];
export type Report = S["Report"];
export type Correction = S["Correction"];
export type Drill = S["Drill"];
export type DrillAttempt = S["DrillAttempt"];
export type DrillSet = S["DrillSet"];
export type VocabOut = S["VocabOut"];
export type SrsCard = S["SrsCard"];
export type Progress = S["Progress"];
export type Usage = S["Usage"];
export type SystemStatus = S["SystemStatus"];
export type HintResponse = S["HintResponse"];
export type Explanation = S["Explanation"];
// Literal unions in the Python schemas are inlined by the exporter rather than
// emitted as named components, so derive them from a type that carries them.
export type Lang = S["LanguageInfo"]["code"];
export type Level = S["ScenarioCard"]["level"];
export type Category = S["ScenarioCard"]["category"];

/** The SSE events a turn can emit. Mirrors the table in the API docs. */
export type TurnEvent =
  | { event: "transcript"; data: { text: string; words: WordTiming[]; provider: string | null; duration_ms: number | null; noisy: boolean } }
  | { event: "no_speech"; data: { reason: string; turn_consumed: false; message: string } }
  | { event: "ai_delta"; data: { text: string } }
  | { event: "ai_audio"; data: { sentence_idx: number; url: string } }
  | { event: "ai_replace"; data: { text: string; reason: string } }
  | { event: "meta"; data: TurnMeta }
  | { event: "turn_state"; data: TurnStateEvent }
  | { event: "error"; data: Problem }
  | { event: "done"; data: Record<string, never> };

export type WordTiming = { w: string; start: number; end: number; prob: number };

export type TurnMeta = {
  goals_done: string[];
  translation_en: string;
  romanization: string;
  suggested_replies: string[];
  end: boolean;
  goals: GoalState[];
  providers?: { llm: string | null; stt: string | null; tts: string | null };
};

export type TurnStateEvent = {
  used: number;
  target: number;
  ended: boolean;
  status: SessionState["status"];
  ai_turn_idx: number;
};

export class ApiError extends Error {
  constructor(
    readonly problem: Problem,
    readonly status: number,
  ) {
    super(problem.detail || problem.title || `Request failed with ${status}`);
    this.name = "ApiError";
  }

  get code(): string {
    return this.problem.code ?? "unknown";
  }

  /** True when retrying later could plausibly succeed. */
  get retryable(): boolean {
    return this.status >= 500 || this.code === "rate-limited";
  }
}

export type ClientOptions = {
  baseUrl: string;
  tokens?: TokenStore;
  /** Called whenever the stored session changes, including on sign-out. */
  onSessionChange?: (session: StoredSession | null) => void;
};

export function createTalkScene(options: ClientOptions) {
  const baseUrl = options.baseUrl.replace(/\/$/, "");
  const tokens = options.tokens ?? browserTokenStore;
  let refreshing: Promise<StoredSession | null> | null = null;

  function session(): StoredSession | null {
    return tokens.read();
  }

  function setSession(pair: TokenPair | null) {
    const next = pair ? store(pair) : null;
    tokens.write(next);
    options.onSessionChange?.(next);
    return next;
  }

  /** Refresh once, shared between concurrent callers. */
  async function refresh(): Promise<StoredSession | null> {
    if (refreshing) return refreshing;
    const current = session();
    if (!current) return null;
    refreshing = (async () => {
      try {
        const response = await fetch(`${baseUrl}/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: current.refresh_token }),
        });
        if (!response.ok) return setSession(null);
        return setSession((await response.json()) as TokenPair);
      } catch {
        // Offline: keep the session and let the caller surface the failure.
        return current;
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  async function accessToken(): Promise<string | null> {
    const current = session();
    if (!current) return null;
    if (isExpired(current)) return (await refresh())?.access_token ?? null;
    return current.access_token;
  }

  const authMiddleware: Middleware = {
    async onRequest({ request }) {
      const token = await accessToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    async onResponse({ response }) {
      if (response.status >= 400 && response.status !== 422) {
        const type = response.headers.get("content-type") ?? "";
        if (type.includes("problem+json") || type.includes("json")) {
          const problem = (await response.clone().json()) as Problem;
          throw new ApiError(problem, response.status);
        }
      }
      return response;
    },
  };

  const api = createClient<paths>({ baseUrl });
  api.use(authMiddleware);

  /** Fetch with the auth header, for the endpoints OpenAPI cannot type. */
  async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const token = await accessToken();
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${baseUrl}${path}`, { ...init, headers });
  }

  return {
    api,
    baseUrl,
    session,
    setSession,
    accessToken,
    authedFetch,

    /** Create an anonymous identity so a learner can start talking immediately. */
    async signInAsGuest(nativeLang: Lang = "en", turnstileToken?: string) {
      const response = await fetch(`${baseUrl}/v1/auth/guest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ native_lang: nativeLang, turnstile_token: turnstileToken ?? null }),
      });
      if (!response.ok) throw new ApiError((await response.json()) as Problem, response.status);
      return setSession((await response.json()) as TokenPair)!;
    },

    async signUp(body: { email: string; password: string; display_name?: string; native_lang?: Lang }) {
      const current = session();
      const response = await fetch(`${baseUrl}/v1/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...body,
          // Carries the guest's recorded sessions into the new account.
          link_guest_token: current?.is_guest ? current.access_token : null,
        }),
      });
      if (!response.ok) throw new ApiError((await response.json()) as Problem, response.status);
      return setSession((await response.json()) as TokenPair)!;
    },

    async signIn(email: string, password: string) {
      const response = await fetch(`${baseUrl}/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) throw new ApiError((await response.json()) as Problem, response.status);
      return setSession((await response.json()) as TokenPair)!;
    },

    signOut() {
      setSession(null);
    },

    /**
     * Submit a turn and stream the reply.
     *
     * Pass `text` for a typed turn or `audio` for a spoken one. `clientTranscript`
     * is the browser's live recognition result: the server folds it into the
     * STT prompt as a spelling bias, and falls back to it if transcription fails.
     */
    async *submitTurn(
      sessionId: string,
      input: {
        text?: string;
        audio?: Blob;
        clientTranscript?: string;
        responseDelayMs?: number;
      },
      signal?: AbortSignal,
    ): AsyncGenerator<TurnEvent> {
      let body: BodyInit;
      const headers = new Headers({ Accept: "text/event-stream" });

      if (input.audio) {
        const form = new FormData();
        form.append("audio", input.audio, "turn.webm");
        if (input.clientTranscript) form.append("client_transcript", input.clientTranscript);
        if (input.responseDelayMs != null)
          form.append("response_delay_ms", String(Math.max(0, Math.round(input.responseDelayMs))));
        body = form; // the browser sets the multipart boundary
      } else {
        headers.set("Content-Type", "application/json");
        body = JSON.stringify({
          text: input.text ?? "",
          // performance.now() deltas are fractional; the API wants milliseconds.
          response_delay_ms: input.responseDelayMs != null ? Math.max(0, Math.round(input.responseDelayMs)) : null,
        });
      }

      const token = await accessToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);

      const response = await fetch(`${baseUrl}/v1/sessions/${sessionId}/turns`, {
        method: "POST",
        headers,
        body,
        signal,
      });

      for await (const message of readEventStream(response, signal)) {
        yield message as TurnEvent;
      }
    },

    /** Absolute URL for an audio path returned by the API. */
    audioUrl(path: string): string {
      return path.startsWith("http") ? path : `${baseUrl}${path}`;
    },

    /** Audio needs the auth header, so it is fetched and turned into a blob URL. */
    async fetchAudio(path: string): Promise<string | null> {
      const response = await authedFetch(path.replace(baseUrl, ""));
      if (!response.ok) return null;
      return URL.createObjectURL(await response.blob());
    },

    async transcribe(audio: Blob, lang: Lang, opts: { prompt?: string; clientTranscript?: string } = {}) {
      const form = new FormData();
      form.append("audio", audio, "clip.webm");
      form.append("lang", lang);
      if (opts.prompt) form.append("prompt", opts.prompt);
      if (opts.clientTranscript) form.append("client_transcript", opts.clientTranscript);
      const response = await authedFetch("/v1/stt", { method: "POST", body: form });
      if (!response.ok) throw new ApiError((await response.json()) as Problem, response.status);
      return (await response.json()) as S["SttResponse"];
    },

    async submitDrillAttempt(drillId: string, audio: Blob) {
      const form = new FormData();
      form.append("audio", audio, "attempt.webm");
      const response = await authedFetch(`/v1/drills/${drillId}/attempts`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new ApiError((await response.json()) as Problem, response.status);
      return (await response.json()) as DrillAttempt;
    },
  };
}

export type TalkSceneClient = ReturnType<typeof createTalkScene>;
