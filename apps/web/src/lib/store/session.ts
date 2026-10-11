"use client";

/**
 * Live conversation state (plan §11.5: "Zustand store for live session").
 *
 * The mic follows the states in §11.3 E:
 *
 *   idle -> recording -> processing -> speaking -> idle
 *
 * The learner's bubble is shown *optimistically* the moment they stop talking,
 * carrying the live caption, and is replaced by the server transcript when it
 * arrives. If the server hears nothing (`no_speech`) the bubble is withdrawn
 * and the turn is not counted — the UI must never charge a turn the API did
 * not.
 */

import type {
  GoalState,
  Lang,
  Level,
  SessionDetail,
  StartSessionResponse,
  TurnEvent,
  TurnOut,
} from "@talkscene/sdk";
import { create } from "zustand";

export type MicState = "idle" | "recording" | "processing" | "speaking";

/** Whether server audio is real speech, the mock's silence, or absent. */
export type ServerVoice = "real" | "silent" | "none";

export type LiveTurn = {
  key: string;
  idx: number | null;
  role: "ai" | "user";
  text: string;
  translation: string | null;
  romanization: string | null;
  suggested: string[];
  audioUrl: string | null;
  audioSentences: number;
  /** User bubble before the server transcript arrives. */
  optimistic?: boolean;
  /** AI bubble still receiving tokens. */
  streaming?: boolean;
  words?: { w: string; start: number; end: number; prob: number }[];
};

type State = {
  sessionId: string | null;
  scenarioId: string | null;
  lang: Lang;
  level: Level;
  status: SessionDetail["status"];
  turns: LiveTurn[];
  goals: GoalState[];
  used: number;
  target: number;
  mic: MicState;
  caption: string;
  notice: string | null;
  error: string | null;
  serverVoice: ServerVoice;
  /** When the last AI audio finished, for measuring response delay. */
  aiFinishedAt: number | null;
  providers: { llm: string | null; stt: string | null; tts: string | null };
  /** The choices made on the brief: input mode and display toggles. */
  options: { input: "voice" | "text"; show_translation: boolean; romanization: boolean; hints: boolean };
};

type Actions = {
  hydrate(detail: SessionDetail | StartSessionResponse): void;
  setMic(mic: MicState): void;
  setCaption(caption: string): void;
  setNotice(notice: string | null): void;
  setError(error: string | null): void;
  markAiFinished(): void;
  beginUserTurn(text: string): string;
  dropOptimistic(): void;
  apply(event: TurnEvent): void;
  reset(): void;
};

const initial: State = {
  sessionId: null,
  scenarioId: null,
  lang: "en",
  level: "A2",
  status: "created",
  turns: [],
  goals: [],
  used: 0,
  target: 12,
  mic: "idle",
  caption: "",
  notice: null,
  error: null,
  serverVoice: "none",
  aiFinishedAt: null,
  providers: { llm: null, stt: null, tts: null },
  options: { input: "voice", show_translation: true, romanization: true, hints: true },
};

let keySeq = 0;
const nextKey = () => `t${Date.now().toString(36)}${(keySeq++).toString(36)}`;

function fromApi(turn: TurnOut): LiveTurn {
  return {
    key: `api-${turn.idx}`,
    idx: turn.idx,
    role: turn.role,
    text: turn.text,
    translation: turn.translation_en ?? null,
    romanization: turn.romanization ?? null,
    suggested: turn.suggested_replies ?? [],
    audioUrl: turn.audio_url ?? null,
    audioSentences: turn.audio_sentences ?? 0,
    words: turn.words ?? [],
  };
}

function voiceOf(provider: string | null | undefined): ServerVoice {
  if (!provider) return "none";
  return provider === "mock" ? "silent" : "real";
}

export const useLive = create<State & Actions>((set, get) => ({
  ...initial,

  hydrate(detail) {
    const turns = "turns" in detail ? detail.turns.map(fromApi) : [fromApi(detail.ai_turn)];
    const apiTurns = "turns" in detail ? detail.turns : [detail.ai_turn];
    const ttsProvider = [...apiTurns].reverse().find((t) => t.role === "ai" && t.tts_provider)?.tts_provider;
    set({
      ...initial,
      sessionId: detail.session_id,
      scenarioId: detail.scenario_id,
      lang: detail.language,
      level: detail.level,
      status: detail.status,
      turns,
      goals: detail.goals,
      used: detail.turn_budget.used,
      target: detail.turn_budget.target,
      serverVoice: voiceOf(ttsProvider ?? null),
      providers: { llm: null, stt: null, tts: ttsProvider ?? null },
      options: {
        input: detail.options?.input === "text" ? "text" : "voice",
        show_translation: detail.options?.show_translation ?? true,
        romanization: detail.options?.romanization ?? true,
        hints: detail.options?.hints ?? true,
      },
      mic: "idle",
    });
  },

  setMic: (mic) => set({ mic }),
  setCaption: (caption) => set({ caption }),
  setNotice: (notice) => set({ notice }),
  setError: (error) => set({ error }),
  markAiFinished: () => set({ aiFinishedAt: performance.now() }),

  beginUserTurn(text) {
    const key = nextKey();
    set((s) => ({
      turns: [
        ...s.turns,
        {
          key,
          idx: null,
          role: "user",
          text,
          translation: null,
          romanization: null,
          suggested: [],
          audioUrl: null,
          audioSentences: 0,
          optimistic: true,
        },
      ],
      notice: null,
      error: null,
      caption: "",
    }));
    return key;
  },

  dropOptimistic() {
    set((s) => ({
      turns: s.turns.filter((t) => !t.optimistic && !(t.streaming && !t.text)),
    }));
  },

  apply(event) {
    const s = get();
    switch (event.event) {
      case "transcript": {
        set({
          turns: s.turns.map((t) =>
            t.optimistic ? { ...t, text: event.data.text, words: event.data.words } : t,
          ),
          notice: event.data.noisy ? "It sounded quiet or noisy there — try moving closer to the mic." : null,
        });
        return;
      }
      case "no_speech": {
        set({
          turns: s.turns.filter((t) => !t.optimistic),
          notice: event.data.message || "I didn't catch that. Try again?",
          mic: "idle",
        });
        return;
      }
      case "ai_delta": {
        const last = s.turns[s.turns.length - 1];
        // The learner's bubble is no longer provisional once the reply starts.
        const settled = s.turns.map((t) => (t.optimistic ? { ...t, optimistic: false } : t));
        if (last?.role === "ai" && last.streaming) {
          set({
            turns: settled.map((t) => (t.key === last.key ? { ...t, text: t.text + event.data.text } : t)),
          });
        } else {
          set({
            turns: [
              ...settled,
              {
                key: nextKey(),
                idx: null,
                role: "ai",
                text: event.data.text,
                translation: null,
                romanization: null,
                suggested: [],
                audioUrl: null,
                audioSentences: 0,
                streaming: true,
              },
            ],
          });
        }
        return;
      }
      case "ai_replace": {
        set({
          turns: s.turns.map((t) => (t.role === "ai" && t.streaming ? { ...t, text: event.data.text } : t)),
        });
        return;
      }
      case "ai_audio": {
        set({
          turns: s.turns.map((t) =>
            t.role === "ai" && t.streaming
              ? { ...t, audioSentences: Math.max(t.audioSentences, event.data.sentence_idx + 1) }
              : t,
          ),
        });
        return;
      }
      case "meta": {
        const tts = event.data.providers?.tts ?? null;
        set({
          goals: event.data.goals,
          turns: s.turns.map((t) =>
            t.role === "ai" && t.streaming
              ? {
                  ...t,
                  translation: event.data.translation_en || null,
                  romanization: event.data.romanization || null,
                  suggested: event.data.suggested_replies ?? [],
                }
              : t,
          ),
          providers: {
            llm: event.data.providers?.llm ?? s.providers.llm,
            stt: event.data.providers?.stt ?? s.providers.stt,
            tts: tts ?? s.providers.tts,
          },
          serverVoice: tts ? voiceOf(tts) : s.serverVoice,
        });
        return;
      }
      case "turn_state": {
        const aiIdx = event.data.ai_turn_idx;
        set({
          used: event.data.used,
          target: event.data.target,
          status: event.data.status,
          turns: s.turns.map((t) => {
            if (t.role === "ai" && t.streaming) {
              return {
                ...t,
                idx: aiIdx,
                streaming: false,
                audioUrl: t.audioSentences ? `/v1/sessions/${s.sessionId}/turns/${aiIdx}/audio` : null,
              };
            }
            if (t.role === "user" && t.idx === null) return { ...t, idx: aiIdx - 1, optimistic: false };
            return t;
          }),
        });
        return;
      }
      case "error": {
        set({
          turns: s.turns.filter((t) => !t.optimistic && !(t.role === "ai" && t.streaming && !t.text)),
          error: event.data.detail || "That turn did not go through. It was not counted.",
          mic: "idle",
        });
        return;
      }
      case "done":
        return;
    }
  },

  reset: () => set(initial),
}));

export function lastAiTurn(turns: LiveTurn[]): LiveTurn | undefined {
  for (let i = turns.length - 1; i >= 0; i--) if (turns[i]?.role === "ai") return turns[i];
  return undefined;
}
