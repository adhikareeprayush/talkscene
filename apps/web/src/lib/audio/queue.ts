/**
 * Ordered playback for AI speech (plan §11.5, "audio queue manager").
 *
 * Sentences arrive one at a time while the model is still writing, and must
 * play in order, gaplessly, and stop instantly when the learner starts talking
 * (barge-in). Two kinds of item share one queue:
 *
 * * `clip` — server-synthesized audio, fetched with the auth header and played
 *   through a single reused `<audio>` element (iOS is far happier with one).
 * * `speak` — the browser's own voice, used whenever the server did not
 *   synthesize (standard voice tier, exhausted premium budget, or the offline
 *   mock provider). This is the always-on fallback from plan §7.4.
 */

import type { Lang } from "@talkscene/sdk";

import { cancelSpeech, speak } from "./speech";

export type QueueItem =
  | { kind: "clip"; url: string; key?: string }
  | { kind: "speak"; text: string; lang: Lang; voiceHint?: string | null; key?: string };

type Listener = (state: { playing: boolean; key: string | null }) => void;

export class AudioQueue {
  private items: QueueItem[] = [];
  private current: QueueItem | null = null;
  private audio: HTMLAudioElement | null = null;
  private blobUrls = new Map<string, string>();
  private listeners = new Set<Listener>();
  private generation = 0;
  rate = 1;

  constructor(private readonly fetchClip: (url: string) => Promise<string | null>) {}

  private element(): HTMLAudioElement {
    if (!this.audio) {
      this.audio = new Audio();
      this.audio.preload = "auto";
      // Keep pitch natural when slowed for the turtle button.
      (this.audio as HTMLAudioElement & { preservesPitch?: boolean }).preservesPitch = true;
    }
    return this.audio;
  }

  /**
   * Call from a user gesture (the first tap). iOS Safari refuses to play audio
   * that was not started inside one, so this primes the element (plan §7.6).
   */
  async unlock(): Promise<boolean> {
    const el = this.element();
    el.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
    try {
      await el.play();
      el.pause();
      return true;
    } catch {
      return false;
    }
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit() {
    const state = { playing: this.current !== null, key: this.current?.key ?? null };
    this.listeners.forEach((listener) => listener(state));
  }

  get playing(): boolean {
    return this.current !== null;
  }

  enqueue(item: QueueItem) {
    this.items.push(item);
    // Start fetching the clip now, so it is ready by the time its turn comes.
    if (item.kind === "clip") void this.resolve(item.url);
    if (!this.current) void this.next(this.generation);
  }

  /** Replace whatever is playing with this item (replay buttons). */
  playNow(item: QueueItem, rate = 1) {
    this.stop();
    this.rate = rate;
    this.enqueue(item);
  }

  /** Barge-in: drop everything, silence immediately. */
  stop() {
    this.generation += 1;
    this.items = [];
    this.current = null;
    if (this.audio) {
      this.audio.pause();
      this.audio.removeAttribute("src");
      this.audio.load();
    }
    cancelSpeech();
    this.rate = 1;
    this.emit();
  }

  private async resolve(url: string): Promise<string | null> {
    const cached = this.blobUrls.get(url);
    if (cached) return cached;
    const blobUrl = await this.fetchClip(url);
    if (blobUrl) this.blobUrls.set(url, blobUrl);
    return blobUrl;
  }

  private async next(generation: number) {
    if (generation !== this.generation) return;
    const item = this.items.shift() ?? null;
    this.current = item;
    this.emit();
    if (!item) return;

    try {
      if (item.kind === "clip") await this.playClip(item.url, generation);
      else await speak(item.text, item.lang, this.rate, item.voiceHint);
    } catch {
      /* one broken clip must not stall the rest of the reply */
    }
    if (generation === this.generation) void this.next(generation);
  }

  private async playClip(url: string, generation: number) {
    const src = await this.resolve(url);
    if (!src || generation !== this.generation) return;
    const el = this.element();
    el.src = src;
    el.playbackRate = this.rate;
    await new Promise<void>((resolve) => {
      const done = () => {
        el.onended = null;
        el.onerror = null;
        resolve();
      };
      el.onended = done;
      el.onerror = done;
      el.play().catch(done);
    });
  }

  dispose() {
    this.stop();
    this.blobUrls.forEach((url) => URL.revokeObjectURL(url));
    this.blobUrls.clear();
    this.listeners.clear();
  }
}
