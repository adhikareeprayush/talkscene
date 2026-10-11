/**
 * Push-to-talk recorder (plan §7.1).
 *
 * MediaRecorder captures Opus (or AAC on Safari, which has no WebM encoder);
 * an AnalyserNode on the same stream drives the level meter and a small energy
 * VAD. The VAD does one job: if nothing above the noise floor was ever heard,
 * the clip is reported as `voiced: false` so the UI can say "didn't catch
 * that" *without* spending an API request on silence.
 *
 * It deliberately does not trim audio in the browser — re-encoding would cost
 * more than it saves, and Whisper ignores leading silence. The server's
 * `no_speech` path is the backstop for anything the gate lets through.
 */

export type RecorderResult = {
  blob: Blob;
  mimeType: string;
  durationMs: number;
  /** Milliseconds of frames above the speech threshold. */
  voicedMs: number;
  voiced: boolean;
  /** Mean level 0..1 over voiced frames; very low means a quiet or distant mic. */
  meanLevel: number;
};

const MAX_DURATION_MS = 30_000; // plan §15: max audio length per turn
const SPEECH_RMS = 0.018;
const MIN_VOICED_MS = 250;

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/ogg;codecs=opus"];
  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

export function recordingSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined"
  );
}

export class MicPermissionError extends Error {
  constructor(readonly reason: "denied" | "unavailable" | "unsupported") {
    super(
      reason === "denied"
        ? "Microphone access was blocked. You can type your replies instead."
        : reason === "unavailable"
          ? "No microphone was found."
          : "This browser cannot record audio. You can type your replies instead.",
    );
    this.name = "MicPermissionError";
  }
}

export class Recorder {
  private stream: MediaStream;
  private ctx: AudioContext;
  private analyser: AnalyserNode;
  private buffer: Float32Array;
  private media: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private voicedMs = 0;
  private voicedLevelSum = 0;
  private voicedFrames = 0;
  private lastFrame = 0;
  private raf = 0;
  private cap: ReturnType<typeof setTimeout> | null = null;
  private onLevel: ((level: number) => void) | null = null;
  private onCap: (() => void) | null = null;
  readonly mimeType: string;

  private constructor(stream: MediaStream) {
    this.stream = stream;
    this.mimeType = pickMimeType();
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    const source = this.ctx.createMediaStreamSource(stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.2;
    source.connect(this.analyser);
    this.buffer = new Float32Array(this.analyser.fftSize);
  }

  static async open(): Promise<Recorder> {
    if (!recordingSupported()) throw new MicPermissionError("unsupported");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      return new Recorder(stream);
    } catch (error) {
      const name = (error as DOMException)?.name;
      if (name === "NotAllowedError" || name === "SecurityError") throw new MicPermissionError("denied");
      if (name === "NotFoundError" || name === "OverconstrainedError") throw new MicPermissionError("unavailable");
      throw new MicPermissionError("unsupported");
    }
  }

  /** Current RMS level, 0..1. Cheap enough to call every animation frame. */
  level(): number {
    this.analyser.getFloatTimeDomainData(this.buffer as Float32Array<ArrayBuffer>);
    let sum = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const v = this.buffer[i] ?? 0;
      sum += v * v;
    }
    return Math.sqrt(sum / this.buffer.length);
  }

  get recording(): boolean {
    return this.media?.state === "recording";
  }

  async start(opts: { onLevel?: (level: number) => void; onCap?: () => void } = {}) {
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.chunks = [];
    this.voicedMs = 0;
    this.voicedLevelSum = 0;
    this.voicedFrames = 0;
    this.onLevel = opts.onLevel ?? null;
    this.onCap = opts.onCap ?? null;

    this.media = new MediaRecorder(this.stream, this.mimeType ? { mimeType: this.mimeType } : undefined);
    this.media.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    this.media.start(250);
    this.startedAt = performance.now();
    this.lastFrame = this.startedAt;
    this.tick();
    this.cap = setTimeout(() => this.onCap?.(), MAX_DURATION_MS);
  }

  private tick = () => {
    const now = performance.now();
    const level = this.level();
    if (level >= SPEECH_RMS) {
      this.voicedMs += now - this.lastFrame;
      this.voicedLevelSum += level;
      this.voicedFrames += 1;
    }
    this.lastFrame = now;
    this.onLevel?.(Math.min(1, level * 6));
    this.raf = requestAnimationFrame(this.tick);
  };

  async stop(): Promise<RecorderResult> {
    cancelAnimationFrame(this.raf);
    if (this.cap) clearTimeout(this.cap);
    const media = this.media;
    if (!media || media.state === "inactive") {
      return { blob: new Blob(), mimeType: this.mimeType, durationMs: 0, voicedMs: 0, voiced: false, meanLevel: 0 };
    }
    const durationMs = performance.now() - this.startedAt;
    await new Promise<void>((resolve) => {
      media.onstop = () => resolve();
      media.stop();
    });
    const type = media.mimeType || this.mimeType || "audio/webm";
    return {
      blob: new Blob(this.chunks, { type }),
      mimeType: type,
      durationMs,
      voicedMs: this.voicedMs,
      voiced: this.voicedMs >= MIN_VOICED_MS,
      meanLevel: this.voicedFrames ? this.voicedLevelSum / this.voicedFrames : 0,
    };
  }

  cancel() {
    cancelAnimationFrame(this.raf);
    if (this.cap) clearTimeout(this.cap);
    if (this.media && this.media.state !== "inactive") {
      this.media.onstop = null;
      this.media.stop();
    }
    this.chunks = [];
  }

  /** Release the device so the OS recording indicator turns off. */
  close() {
    this.cancel();
    this.stream.getTracks().forEach((track) => track.stop());
    void this.ctx.close().catch(() => {});
  }
}
