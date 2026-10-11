/**
 * Web Speech API wrappers: live captions and the always-on browser voice.
 *
 * Live recognition is a *caption*, not the transcript — the server's Whisper
 * result is final (plan §3.2). It also doubles as a spelling hint the server
 * folds into the STT prompt. Firefox has no SpeechRecognition, in which case
 * captions are simply hidden (plan §11.6).
 *
 * Privacy note surfaced in Settings: Chrome sends recognition audio to Google.
 */

import type { Lang } from "@talkscene/sdk";

import { LANGS } from "../lang";

type RecognitionCtor = new () => SpeechRecognitionLike;
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function recognitionSupported(): boolean {
  return recognitionCtor() !== null;
}

export function synthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export type LiveCaption = {
  /** Stop and resolve with the best transcript heard so far. */
  stop(): Promise<string>;
  abort(): void;
};

export function startLiveCaption(lang: Lang, onText: (text: string) => void): LiveCaption | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const recognition = new Ctor();
  recognition.lang = LANGS[lang].bcp47;
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  let finalText = "";
  let interim = "";
  let ended = false;
  let resolveEnd: (() => void) | null = null;

  recognition.onresult = (event) => {
    interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (!result) continue;
      const text = result[0]?.transcript ?? "";
      if (result.isFinal) finalText += text;
      else interim += text;
    }
    onText((finalText + interim).trim());
  };
  recognition.onerror = () => {
    /* captions are best-effort: the server transcript is authoritative */
  };
  recognition.onend = () => {
    ended = true;
    resolveEnd?.();
  };

  try {
    recognition.start();
  } catch {
    return null;
  }

  return {
    stop() {
      return new Promise<string>((resolve) => {
        const finish = () => resolve((finalText + interim).trim());
        if (ended) return finish();
        resolveEnd = finish;
        try {
          recognition.stop();
        } catch {
          finish();
        }
        // Some engines never fire `end`; do not hang the turn on them.
        setTimeout(finish, 900);
      });
    },
    abort() {
      try {
        recognition.abort();
      } catch {
        /* already stopped */
      }
    },
  };
}

// ── synthesis ───────────────────────────────────────────────────────────────
let voicesReady: Promise<SpeechSynthesisVoice[]> | null = null;

function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!synthesisSupported()) return Promise.resolve([]);
  if (voicesReady) return voicesReady;
  voicesReady = new Promise((resolve) => {
    const synth = window.speechSynthesis;
    const now = synth.getVoices();
    if (now.length) return resolve(now);
    // Chrome loads voices asynchronously; Safari sometimes never fires the event.
    const done = () => resolve(synth.getVoices());
    synth.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1200);
  });
  return voicesReady;
}

export async function bestVoice(lang: Lang, hint?: string | null): Promise<SpeechSynthesisVoice | null> {
  const voices = await loadVoices();
  const tag = LANGS[lang].bcp47.toLowerCase();
  const prefix = tag.slice(0, 2);
  const matching = voices.filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith(prefix));
  if (!matching.length) return null;
  const wantFemale = hint?.includes("female");
  const score = (v: SpeechSynthesisVoice) =>
    (v.lang.toLowerCase().replace("_", "-") === tag ? 4 : 0) +
    (/natural|neural|premium|enhanced|online/i.test(v.name) ? 3 : 0) +
    (v.localService ? 1 : 0) +
    (wantFemale !== undefined && /female|woman|samantha|yuna|kyoko|anna|nanami/i.test(v.name) === wantFemale ? 1 : 0);
  return matching.sort((a, b) => score(b) - score(a))[0] ?? null;
}

export function cancelSpeech() {
  if (synthesisSupported()) window.speechSynthesis.cancel();
}

/** Rough spoken duration, used to bound how long we wait for a voice. */
function estimateMs(text: string, lang: Lang, rate: number): number {
  const perSecond = LANGS[lang].cjk ? 6 : 14;
  return 800 + (text.length / perSecond / Math.max(rate, 0.5)) * 1000;
}

/**
 * Speak a line with the browser voice. Resolves when it finishes, is
 * cancelled, or plainly is not going to: some engines (headless browsers, a
 * few Linux and Safari builds) never fire `end`, and a promise that never
 * settles would freeze the conversation in "speaking" forever.
 */
export async function speak(text: string, lang: Lang, rate = 1, hint?: string | null): Promise<void> {
  if (!synthesisSupported() || !text.trim()) return;
  const voices = await loadVoices();
  // No voices at all: there is nothing that could speak, so do not wait.
  if (!voices.length) return;
  const voice = await bestVoice(lang, hint);
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(watchdog);
      resolve();
    };
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = LANGS[lang].bcp47;
    if (voice) utterance.voice = voice;
    // A1 learners get a slower default (plan §6.2); the caller passes the rate.
    utterance.rate = Math.max(0.5, Math.min(1.5, rate));
    utterance.onend = done;
    utterance.onerror = done;
    const watchdog = setTimeout(done, Math.min(30_000, estimateMs(text, lang, utterance.rate) + 2500));
    window.speechSynthesis.speak(utterance);
  });
}
