"use client";

/**
 * The single SDK instance plus TanStack Query hooks.
 *
 * Server state (catalog, sessions, reports, vocab) lives in the query cache;
 * the live conversation lives in the zustand store (plan §11.5). Components
 * import hooks from here and never call `fetch` themselves — if a screen needs
 * something this module cannot provide, the API is incomplete.
 */

import {
  ApiError,
  createTalkScene,
  type Lang,
  type Level,
  type Me,
  type MeUpdate,
  type Report,
} from "@talkscene/sdk";
import {
  QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const SESSION_EVENT = "talkscene:session";

export const client = createTalkScene({
  baseUrl: API_URL,
  // Lets `useSessionInfo` re-render when this tab signs in or out.
  onSessionChange: () => {
    if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_EVENT));
  },
});

// ── who is signed in, readable during render ────────────────────────────────
// Pages are prerendered on the server, where storage holds no token. Reading
// `client.session()` during render - including in a query's `enabled` flag -
// makes the server HTML disagree with the client's first render. A server
// snapshot keeps both sides identical during hydration (see client-state.ts).
type SessionInfo = { signedIn: boolean; guest: boolean };
const SERVER_SESSION: SessionInfo = { signedIn: false, guest: true };
let cached: SessionInfo = SERVER_SESSION;

function sessionSnapshot(): SessionInfo {
  const session = client.session();
  const signedIn = session !== null;
  const guest = session?.is_guest ?? true;
  // Snapshots must be referentially stable between unchanged reads.
  if (cached.signedIn !== signedIn || cached.guest !== guest) cached = { signedIn, guest };
  return cached;
}

function subscribeSession(callback: () => void) {
  window.addEventListener("storage", callback); // other tabs
  window.addEventListener(SESSION_EVENT, callback); // this tab
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(SESSION_EVENT, callback);
  };
}

/** Who is using the app, safe to read during render. */
export function useSessionInfo(): SessionInfo {
  return useSyncExternalStore(subscribeSession, sessionSnapshot, () => SERVER_SESSION);
}

export const api = client.api;

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) => {
          // Retrying a 4xx never helps and burns rate-limit budget.
          if (error instanceof ApiError && !error.retryable) return false;
          return count < 2;
        },
        refetchOnWindowFocus: false,
      },
    },
  });
}

/** Unwrap an openapi-fetch result, turning problem documents into ApiError. */
function data<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  if (result.error && typeof result.error === "object" && "detail" in (result.error as object)) {
    throw new ApiError(result.error as never, result.response.status);
  }
  throw new Error(`Request failed with ${result.response.status}`);
}

export const keys = {
  me: ["me"] as const,
  status: ["status"] as const,
  languages: ["languages"] as const,
  scenarios: (params: object) => ["scenarios", params] as const,
  scenario: (id: string) => ["scenario", id] as const,
  sessions: (lang?: string) => ["sessions", lang ?? "all"] as const,
  session: (id: string) => ["session", id] as const,
  report: (id: string) => ["report", id] as const,
  drills: (sessionId?: string) => ["drills", sessionId ?? "all"] as const,
  drill: (id: string) => ["drill", id] as const,
  vocab: (lang?: string) => ["vocab", lang ?? "all"] as const,
  due: (lang?: string) => ["due", lang ?? "all"] as const,
  progress: ["progress"] as const,
  usage: ["usage"] as const,
};

// ── identity ────────────────────────────────────────────────────────────────
export function useMe(options?: Partial<UseQueryOptions<Me>>) {
  const { signedIn } = useSessionInfo();
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => data(await api.GET("/v1/me")),
    enabled: signedIn,
    ...options,
  });
}

/** Make sure there is *some* identity before a screen that needs one. */
export async function ensureSession(nativeLang: Lang = "en") {
  if (client.session()) return client.session()!;
  return client.signInAsGuest(nativeLang);
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: MeUpdate) => data(await api.PATCH("/v1/me", { body })),
    onSuccess: (me) => qc.setQueryData(keys.me, me),
  });
}

export function useStatus() {
  return useQuery({
    queryKey: keys.status,
    queryFn: async () => data(await api.GET("/v1/status")),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

// ── catalog ─────────────────────────────────────────────────────────────────
export function useLanguages() {
  return useQuery({
    queryKey: keys.languages,
    queryFn: async () => data(await api.GET("/v1/languages")),
    staleTime: 10 * 60_000,
  });
}

export type ScenarioQuery = {
  lang?: Lang;
  level?: Level;
  category?: string;
  q?: string;
  sort?: "recommended" | "newest" | "shortest";
  limit?: number;
};

export function useScenarios(params: ScenarioQuery) {
  return useQuery({
    queryKey: keys.scenarios(params),
    queryFn: async () =>
      data(
        await api.GET("/v1/scenarios", {
          params: { query: { limit: 60, ...params } as never },
        }),
      ),
  });
}

export function useScenario(id: string) {
  return useQuery({
    queryKey: keys.scenario(id),
    queryFn: async () =>
      data(await api.GET("/v1/scenarios/{scenario_id}", { params: { path: { scenario_id: id } } })),
    enabled: Boolean(id),
  });
}

// ── sessions ────────────────────────────────────────────────────────────────
export function useSessions(language?: string) {
  const { signedIn } = useSessionInfo();
  return useQuery({
    queryKey: keys.sessions(language),
    queryFn: async () =>
      data(
        await api.GET("/v1/sessions", {
          params: { query: { limit: 50, ...(language ? { language } : {}) } },
        }),
      ),
    enabled: signedIn,
  });
}

export function useSession(id: string) {
  return useQuery({
    queryKey: keys.session(id),
    queryFn: async () =>
      data(await api.GET("/v1/sessions/{session_id}", { params: { path: { session_id: id } } })),
    enabled: Boolean(id),
    staleTime: 5_000,
  });
}

export function useStartSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      scenario_id: string;
      target_turns: number;
      options: Record<string, unknown>;
    }) => {
      await ensureSession();
      return data(await api.POST("/v1/sessions", { body: body as never }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

/**
 * Poll the report: the API answers 202 while analysing and 200 when ready.
 * openapi-fetch treats both as success, so the shape decides.
 */
export function useReport(sessionId: string, enabled = true) {
  return useQuery({
    queryKey: keys.report(sessionId),
    queryFn: async (): Promise<{ status: "ready"; report: Report } | { status: "analyzing"; eta: number }> => {
      const result = await api.GET("/v1/sessions/{session_id}/report", {
        params: { path: { session_id: sessionId } },
      });
      const body = data(result) as unknown as Report | { status: "analyzing"; eta_s: number };
      if (result.response.status === 202 || (body as { status?: string }).status === "analyzing") {
        return { status: "analyzing", eta: (body as { eta_s: number }).eta_s ?? 6 };
      }
      return { status: "ready", report: body as Report };
    },
    enabled: enabled && Boolean(sessionId),
    refetchInterval: (query) => (query.state.data?.status === "analyzing" ? 1500 : false),
    staleTime: Infinity,
  });
}

export async function endSession(sessionId: string) {
  return data(
    await api.POST("/v1/sessions/{session_id}/end", { params: { path: { session_id: sessionId } } }),
  );
}

export async function requestHint(
  sessionId: string,
  body: { type: "suggest" | "translate" | "explain" | "slow"; target?: string; turn_idx?: number },
) {
  return data(
    await api.POST("/v1/sessions/{session_id}/hint", {
      params: { path: { session_id: sessionId } },
      body: body as never,
    }),
  );
}

// ── drills ──────────────────────────────────────────────────────────────────
export function useDrillSet(sessionId: string) {
  return useQuery({
    queryKey: keys.drills(sessionId),
    queryFn: async () => data(await api.POST("/v1/drills", { body: { session_id: sessionId } })),
    enabled: Boolean(sessionId),
    staleTime: Infinity,
  });
}

// ── vocabulary + SRS ────────────────────────────────────────────────────────
export function useVocab(lang?: string) {
  const { signedIn, guest } = useSessionInfo();
  return useQuery({
    queryKey: keys.vocab(lang),
    queryFn: async () =>
      data(await api.GET("/v1/vocab", { params: { query: { limit: 200, ...(lang ? { language: lang } : {}) } } })),
    enabled: signedIn && !guest,
  });
}

export function useDueCards(lang?: string) {
  const { signedIn, guest } = useSessionInfo();
  return useQuery({
    queryKey: keys.due(lang),
    queryFn: async () =>
      data(await api.GET("/v1/srs/due", { params: { query: { limit: 50, ...(lang ? { language: lang } : {}) } } })),
    enabled: signedIn && !guest,
  });
}

export function useSaveWord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      language: Lang;
      term: string;
      meaning: string;
      reading?: string | null;
      example?: string | null;
      source_session_id?: string | null;
    }) => data(await api.POST("/v1/vocab", { body: body as never })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vocab"] });
      qc.invalidateQueries({ queryKey: ["due"] });
      qc.invalidateQueries({ queryKey: keys.progress });
    },
  });
}

export function useReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, rating }: { cardId: string; rating: 1 | 2 | 3 | 4 }) =>
      data(
        await api.POST("/v1/srs/{card_id}/review", {
          params: { path: { card_id: cardId } },
          body: { rating },
        }),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.progress });
      qc.invalidateQueries({ queryKey: ["vocab"] });
    },
  });
}

// ── progress + usage ────────────────────────────────────────────────────────
export function useProgress() {
  const { signedIn } = useSessionInfo();
  return useQuery({
    queryKey: keys.progress,
    queryFn: async () => data(await api.GET("/v1/progress", { params: { query: { days: 35 } } })),
    enabled: signedIn,
  });
}

export function useUsage() {
  const { signedIn } = useSessionInfo();
  return useQuery({
    queryKey: keys.usage,
    queryFn: async () => data(await api.GET("/v1/usage")),
    enabled: signedIn,
  });
}

export function problemMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
