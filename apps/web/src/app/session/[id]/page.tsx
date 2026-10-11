"use client";

import type { Explanation, Lang, ScenarioBrief, TurnEvent } from "@talkscene/sdk";
import Link from "next/link";
import { useSessionInfo } from "@/lib/client-state";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatBubble, GoalChecklist, TurnProgress } from "@/components/Conversation";
import { ErrorBanner } from "@/components/feedback";
import { Icon } from "@/components/Icon";
import { MicButton } from "@/components/MicButton";
import { Sheet } from "@/components/Sheet";
import { Button, IconButton, Spinner } from "@/components/ui";
import { client, endSession, problemMessage, requestHint, useScenario, useSession, useSaveWord } from "@/lib/api";
import { AudioQueue } from "@/lib/audio/queue";
import { MicPermissionError, Recorder, recordingSupported } from "@/lib/audio/recorder";
import { recognitionSupported, startLiveCaption, type LiveCaption } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { useImeSubmit } from "@/lib/ime";
import { applyLang } from "@/lib/lang";
import { lastAiTurn, useLive, type LiveTurn } from "@/lib/store/session";
import { usePrefs } from "@/lib/store/prefs";

const NUDGE_AFTER_MS = 20_000; // plan §6.3: nudge after 20 s of silence, no penalty
const MIN_TURNS_TO_END = 4;

export default function LiveSession() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const live = useLive();
  const detail = useSession(live.sessionId === id ? "" : id);
  const scenario = useScenario(live.scenarioId ?? detail.data?.scenario_id ?? "");
  const prefs = usePrefs();

  // ── hydrate from the server when we did not arrive from the brief ─────────
  useEffect(() => {
    if (detail.data && live.sessionId !== id) useLive.getState().hydrate(detail.data);
  }, [detail.data, id, live.sessionId]);
  useEffect(() => {
    if (live.sessionId !== id) return;
    if (live.status === "analyzing" || live.status === "completed") router.replace(`/session/${id}/report`);
  }, [live.status, live.sessionId, id, router]);
  useEffect(() => {
    applyLang(live.lang);
    return () => applyLang(usePrefs.getState().lang);
  }, [live.lang]);

  // ── audio ────────────────────────────────────────────────────────────────
  const queue = useMemo(() => (typeof window === "undefined" ? null : new AudioQueue((url) => client.fetchAudio(url))), []);
  const [playingKey, setPlayingKey] = useState<string | null>(null);
  const [soundUnlocked, setSoundUnlocked] = useState(false);
  useEffect(() => {
    if (!queue) return;
    const unsubscribe = queue.subscribe(({ playing, key }) => {
      setPlayingKey(key);
      const s = useLive.getState();
      if (playing) {
        // Never override a learner who has already started talking (barge-in).
        if (s.mic === "idle" || s.mic === "processing") s.setMic("speaking");
      } else {
        if (s.mic === "speaking") s.setMic("idle");
        s.markAiFinished();
      }
    });
    return () => {
      unsubscribe();
      queue.dispose();
    };
  }, [queue]);

  const voiceHint = scenario.data?.voice?.browser_hint ?? null;
  const baseRate = live.level === "A1" ? 0.85 : 1;

  const sayTurn = useCallback(
    (turn: LiveTurn, rate = baseRate) => {
      if (!queue || !turn.text) return;
      const voice = useLive.getState().serverVoice;
      if (voice === "real" && turn.audioUrl && turn.audioSentences > 0) {
        queue.stop();
        queue.rate = rate;
        for (let i = 0; i < turn.audioSentences; i++) {
          queue.enqueue({ kind: "clip", url: `${turn.audioUrl}?s=${i}`, key: turn.key });
        }
      } else {
        queue.playNow({ kind: "speak", text: turn.text, lang: live.lang, voiceHint, key: turn.key }, rate);
      }
    },
    [queue, live.lang, voiceHint, baseRate],
  );

  const unlockAndGreet = async () => {
    if (!queue) return;
    await queue.unlock();
    setSoundUnlocked(true);
    const opening = lastAiTurn(useLive.getState().turns);
    if (opening && useLive.getState().turns.length === 1) sayTurn(opening);
  };

  // ── streaming a turn ─────────────────────────────────────────────────────
  const abort = useRef<AbortController | null>(null);
  const clipsThisTurn = useRef(0);

  const runTurn = useCallback(
    async (input: { text?: string; audio?: Blob; clientTranscript?: string }, optimisticText: string) => {
      const s = useLive.getState();
      if (!s.sessionId) return;
      const delay = s.aiFinishedAt ? performance.now() - s.aiFinishedAt : undefined;
      s.beginUserTurn(optimisticText);
      s.setMic("processing");
      clipsThisTurn.current = 0;
      abort.current = new AbortController();

      try {
        for await (const event of client.submitTurn(s.sessionId, { ...input, responseDelayMs: delay }, abort.current.signal)) {
          useLive.getState().apply(event);
          onEvent(event);
        }
      } catch (error) {
        useLive.getState().dropOptimistic();
        useLive.getState().setError(problemMessage(error));
        useLive.getState().setMic("idle");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const onEvent = (event: TurnEvent) => {
    const s = useLive.getState();
    if (event.event === "ai_audio" && s.serverVoice === "real" && queue) {
      // Sentence 1 plays while the model is still writing sentence 2 (plan §7.4).
      queue.enqueue({ kind: "clip", url: event.data.url, key: "streaming" });
      clipsThisTurn.current += 1;
      if (s.mic === "processing") s.setMic("speaking");
    }
    if (event.event === "done") {
      const turn = lastAiTurn(s.turns);
      const voice = useLive.getState().serverVoice;
      if (turn && !turn.streaming && (voice !== "real" || clipsThisTurn.current === 0) && queue) {
        queue.enqueue({ kind: "speak", text: turn.text, lang: s.lang, voiceHint, key: turn.key });
      }
      // The stream is over: the mic is free again unless the character is
      // still talking, in which case the queue moves it to idle when done.
      const live = useLive.getState();
      if (live.mic === "processing") live.setMic(queue?.playing ? "speaking" : "idle");
    }
  };

  // ── microphone ───────────────────────────────────────────────────────────
  const recorder = useRef<Recorder | null>(null);
  const caption = useRef<LiveCaption | null>(null);
  const levelRef = useRef(0);
  // Capabilities are probed after mount: the server has no microphone, and an
  // initial value that differs between server and client breaks hydration.
  const [micBlocked, setMicBlocked] = useState(false);
  const [captionsAvailable, setCaptionsAvailable] = useState(true);
  useEffect(() => {
    setMicBlocked(!recordingSupported());
    setCaptionsAvailable(recognitionSupported());
  }, []);
  const [typing, setTyping] = useState(live.options.input === "text");
  const [draft, setDraft] = useState("");

  // Honour the input mode chosen on the brief once the session is loaded.
  useEffect(() => {
    if (live.sessionId === id) setTyping((current) => current || live.options.input === "text");
  }, [live.sessionId, live.options.input, id]);

  const startRecording = async () => {
    const s = useLive.getState();
    queue?.stop();
    s.setNotice(null);
    s.setError(null);
    if (!soundUnlocked && queue) {
      void queue.unlock();
      setSoundUnlocked(true);
    }
    try {
      recorder.current ??= await Recorder.open();
    } catch (error) {
      setMicBlocked(true);
      setTyping(true);
      s.setNotice(error instanceof MicPermissionError ? error.message : "The microphone is unavailable — type your reply instead.");
      return;
    }
    s.setMic("recording");
    caption.current = startLiveCaption(s.lang, (text) => useLive.getState().setCaption(text));
    await recorder.current.start({
      onLevel: (level) => (levelRef.current = level),
      onCap: () => void stopRecording(),
    });
  };

  const stopRecording = async () => {
    const s = useLive.getState();
    if (!recorder.current || s.mic !== "recording") return;
    s.setMic("processing");
    const [result, heard] = await Promise.all([recorder.current.stop(), caption.current?.stop() ?? Promise.resolve("")]);
    caption.current = null;
    levelRef.current = 0;
    // Silence never reaches the API, so it can never cost a turn.
    if (!result.voiced && !heard) {
      s.setMic("idle");
      s.setNotice("I didn't catch that. Try again — hold the button while you speak.");
      return;
    }
    await runTurn({ audio: result.blob, clientTranscript: heard || undefined }, heard || "…");
  };

  const cancelRecording = () => {
    recorder.current?.cancel();
    caption.current?.abort();
    caption.current = null;
    levelRef.current = 0;
    useLive.getState().setMic("idle");
    useLive.getState().setCaption("");
  };

  useEffect(() => () => {
    abort.current?.abort();
    recorder.current?.close();
    caption.current?.abort();
  }, []);

  const sendText = () => {
    const text = draft.trim();
    if (!text || live.mic === "processing") return;
    setDraft("");
    queue?.stop();
    void runTurn({ text }, text);
  };
  const ime = useImeSubmit(sendText);

  // ── silence nudge ────────────────────────────────────────────────────────
  const [nudge, setNudge] = useState(false);
  useEffect(() => {
    setNudge(false);
    if (live.mic !== "idle" || live.status !== "active") return;
    const timer = setTimeout(() => setNudge(true), NUDGE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [live.mic, live.turns.length, live.status, draft]);

  // ── hints, words, settings ───────────────────────────────────────────────
  const [hintsOpen, setHintsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [word, setWord] = useState<string | null>(null);
  // Translations start hidden: tapping to reveal is the point of practice.
  const [showTranslation, setShowTranslation] = useState(false);
  const [showRomanization, setShowRomanization] = useState(live.options.romanization);
  const [rateChoice, setRateChoice] = useState(1);

  // ── ending ───────────────────────────────────────────────────────────────
  const [ending, setEnding] = useState(false);
  const ended = live.status === "analyzing" || live.status === "completed";
  const finish = async () => {
    setEnding(true);
    queue?.stop();
    try {
      await endSession(id);
      router.push(`/session/${id}/report`);
    } catch (error) {
      setEnding(false);
      useLive.getState().setError(problemMessage(error));
    }
  };
  // When the budget runs out, let the last line finish, then move on.
  useEffect(() => {
    if (!ended || live.mic === "speaking") return;
    const timer = setTimeout(() => router.push(`/session/${id}/report`), 2600);
    return () => clearTimeout(timer);
  }, [ended, live.mic, id, router]);

  // ── autoscroll ───────────────────────────────────────────────────────────
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [live.turns, live.caption]);

  const s: ScenarioBrief | undefined = scenario.data;
  if (live.sessionId !== id) {
    return (
      <div className="grid min-h-dvh place-items-center">
        {detail.error ? (
          <div className="max-w-sm px-6 text-center">
            <ErrorBanner message={problemMessage(detail.error)} />
            <Link href="/home" className="tap mt-4 inline-flex items-center text-sm font-medium text-accent-ink">Back to home</Link>
          </div>
        ) : (
          <Spinner size={28} className="text-accent" />
        )}
      </div>
    );
  }

  const persona = s?.persona.name ?? "Your partner";
  const last = lastAiTurn(live.turns);
  const canEnd = live.used >= MIN_TURNS_TO_END && !ended;
  const lang = live.lang as Lang;

  return (
    <div className="flex h-dvh flex-col md:grid md:grid-cols-[1fr_320px]">
      <section className="relative flex min-h-0 flex-1 flex-col">
        <div aria-hidden className="glow-accent pointer-events-none absolute inset-x-0 top-0 h-56" />

        {/* ── top bar ─────────────────────────────────────────────── */}
        <header className="relative z-10 border-b border-line/70 bg-paper/80 px-3 pb-2.5 pt-2 backdrop-blur-xl">
          <div className="flex items-center gap-1">
            <Link href={s ? `/scenarios/${s.id}` : "/home"} aria-label="Leave conversation" className="tap grid place-items-center rounded-full text-ink-2 hover:bg-paper-2">
              <Icon name="back" size={22} />
            </Link>
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-[15px] font-semibold text-ink">{s?.title.en ?? "Conversation"}</h1>
              <TurnProgress used={live.used} target={live.target} />
            </div>
            {canEnd ? (
              <Button size="sm" variant="secondary" onClick={finish} disabled={ending} className="hidden sm:inline-flex">
                {ending ? "Finishing…" : "Finish & get feedback"}
              </Button>
            ) : null}
            <IconButton icon="more" label="Conversation settings" onClick={() => setSettingsOpen(true)} />
          </div>
          <GoalChecklist goals={live.goals} compact className="mt-2 md:hidden" />
        </header>

        {/* ── transcript ──────────────────────────────────────────── */}
        <div ref={scroller} className="relative z-0 flex-1 overflow-y-auto px-4 py-6" aria-live="polite" aria-relevant="additions">
          <div className="mx-auto max-w-2xl space-y-5">
            <p className="text-center text-[12px] text-ink-3">{s?.setting}</p>
            {live.turns.map((turn) => (
              <ChatBubble
                key={turn.key}
                turn={turn}
                lang={lang}
                persona={persona}
                playing={playingKey === turn.key}
                showTranslation={showTranslation}
                showRomanization={showRomanization}
                onReplay={() => sayTurn(turn, rateChoice * baseRate)}
                onSlow={() => sayTurn(turn, 0.75)}
                onWord={(w) => setWord(w)}
              />
            ))}
            {live.mic === "recording" && live.caption ? (
              <div className="fade-in flex justify-end pl-10">
                <p lang={lang} className="target max-w-[85%] rounded-[22px] rounded-br-md border border-dashed border-line-strong px-4 py-3 text-[17px] text-ink-2">
                  {live.caption}
                </p>
              </div>
            ) : null}
            {live.mic === "processing" && !live.turns.some((t) => t.streaming) ? (
              <div className="fade-in flex items-center gap-2 pl-12 text-[13px] text-ink-3">
                <Spinner size={14} /> {persona} is thinking…
              </div>
            ) : null}
            {ended ? (
              <div className="card reveal mx-auto max-w-sm p-6 text-center">
                <p className="emoji text-3xl" aria-hidden>🎉</p>
                <p className="mt-2 font-display text-2xl text-ink">Great job!</p>
                <p className="mt-1 text-[14px] text-ink-2">Analysing your conversation…</p>
                <Button className="mt-4" onClick={() => router.push(`/session/${id}/report`)} iconRight="arrow">
                  See my feedback
                </Button>
              </div>
            ) : null}
          </div>
        </div>

        {/* ── composer ────────────────────────────────────────────── */}
        <footer className="relative z-10 border-t border-line/70 bg-paper/85 px-4 pb-4 pt-3 backdrop-blur-xl safe-bottom">
          <div className="mx-auto max-w-2xl">
            {live.error ? <ErrorBanner className="mb-3" message={live.error} onRetry={() => useLive.getState().setError(null)} fallback={!typing ? { label: "Type instead", onClick: () => setTyping(true) } : undefined} /> : null}
            {live.notice ? <ErrorBanner className="mb-3" tone="info" message={live.notice} /> : null}
            {nudge && !ended ? (
              <div className="fade-in mb-3 flex items-center justify-between gap-3 rounded-2xl bg-accent-soft px-4 py-2.5 text-[14px] text-accent-ink">
                <span>Take your time. Stuck for words?</span>
                <button className="tap rounded-full px-3 font-semibold" onClick={() => setHintsOpen(true)}>Get a hint</button>
              </div>
            ) : null}
            {!soundUnlocked && live.turns.length === 1 ? (
              <button onClick={unlockAndGreet} className="fade-in mb-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-card py-3 text-[14px] font-medium text-ink hairline">
                <Icon name="speaker" size={18} /> Tap to hear {persona}
              </button>
            ) : null}

            {typing || micBlocked ? (
              <div className="flex items-end gap-2">
                <IconButton icon="bulb" label="Hints" onClick={() => setHintsOpen(true)} disabled={ended} />
                <label className="sr-only" htmlFor="reply">Your reply</label>
                <textarea
                  id="reply"
                  lang={lang}
                  rows={1}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  {...ime}
                  disabled={ended || live.mic === "processing"}
                  placeholder="Type your reply…"
                  className="target max-h-36 min-h-12 flex-1 resize-none rounded-[22px] bg-card px-4 py-3 text-[17px] text-ink outline-none hairline placeholder:text-ink-3 focus-visible:shadow-[inset_0_0_0_2px_var(--accent)]"
                />
                {draft.trim() ? (
                  <button onClick={sendText} disabled={live.mic === "processing"} aria-label="Send" className="tap grid size-12 place-items-center rounded-full bg-accent text-on-accent">
                    <Icon name="arrow" size={20} />
                  </button>
                ) : !micBlocked ? (
                  <IconButton icon="mic" label="Switch to voice" onClick={() => setTyping(false)} />
                ) : null}
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <IconButton icon="bulb" label="Hints" onClick={() => setHintsOpen(true)} disabled={ended} className="size-12" />
                <MicButton
                  state={live.mic}
                  levelRef={levelRef}
                  speakerName={persona}
                  disabled={ended}
                  onStart={() => void startRecording()}
                  onStop={() => void stopRecording()}
                  onCancel={cancelRecording}
                  onInterrupt={() => void startRecording()}
                />
                <IconButton icon="keyboard" label="Type instead" onClick={() => setTyping(true)} disabled={ended} className="size-12" />
              </div>
            )}
            {canEnd ? (
              <button onClick={finish} disabled={ending} className="tap mt-2 w-full rounded-full text-[13px] font-medium text-ink-3 hover:text-ink sm:hidden">
                {ending ? "Finishing…" : "Finish and see feedback"}
              </button>
            ) : null}
            {!captionsAvailable && !typing && !micBlocked ? (
              <p className="mt-1 text-center text-[11px] text-ink-3">Live captions are not available in this browser — your speech is still transcribed.</p>
            ) : null}
          </div>
        </footer>
      </section>

      {/* ── side panel (desktop) ───────────────────────────────────── */}
      <aside className="hidden border-l border-line bg-paper-2/50 p-6 md:block md:overflow-y-auto" aria-label="Scene details">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">Goals</p>
        <GoalChecklist className="mt-3" goals={live.goals} />
        {s?.useful_phrases.length ? (
          <>
            <p className="mt-8 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">Phrases</p>
            <ul className="mt-3 space-y-2">
              {s.useful_phrases.map((p) => (
                <li key={p.text}>
                  <button onClick={() => queue?.playNow({ kind: "speak", text: p.text, lang, voiceHint }, baseRate)} className="w-full rounded-xl p-2 text-left transition hover:bg-card">
                    <span lang={lang} className="target block text-[15px] text-ink">{p.text}</span>
                    <span className="block text-[12.5px] text-ink-3">{p.meaning}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <p className="mt-8 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">You are</p>
        <p className="mt-2 text-[14px] text-ink-2">{s?.user_role}</p>
      </aside>

      <HintSheet
        open={hintsOpen}
        onClose={() => setHintsOpen(false)}
        sessionId={id}
        lang={lang}
        last={last}
        phrases={s?.useful_phrases ?? []}
        onUse={(text) => {
          setHintsOpen(false);
          setTyping(true);
          setDraft(text);
        }}
        onHear={(text) => queue?.playNow({ kind: "speak", text, lang, voiceHint }, baseRate)}
      />
      <WordSheet word={word} onClose={() => setWord(null)} sessionId={id} lang={lang} onHear={(text) => queue?.playNow({ kind: "speak", text, lang, voiceHint }, baseRate)} />
      <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Conversation settings">
        <div className="space-y-5">
          <SettingRow label="Show translations" checked={showTranslation} onChange={setShowTranslation} />
          <SettingRow label={lang === "ja" ? "Show reading (rōmaji)" : "Show romanization"} checked={showRomanization} onChange={setShowRomanization} disabled={lang === "de" || lang === "en"} />
          <div>
            <p className="text-[14px] font-semibold text-ink">Voice speed</p>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[0.85, 1, 1.15].map((r) => (
                <button key={r} onClick={() => setRateChoice(r)} aria-pressed={rateChoice === r} className={cx("tap rounded-2xl text-[14px] font-medium", rateChoice === r ? "bg-ink text-paper" : "bg-paper-2 text-ink-2")}>
                  {r === 1 ? "Normal" : r < 1 ? "Slower" : "Faster"}
                </button>
              ))}
            </div>
          </div>
          <p className="text-[12.5px] text-ink-3">
            Voice: {live.serverVoice === "real" ? "premium neural voice" : "your browser’s built-in voice"} · Level {live.level} · {prefs.lang === lang ? "your main language" : "practice language"}
          </p>
          {canEnd ? <Button className="w-full" variant="secondary" onClick={finish}>Finish and see feedback</Button> : null}
        </div>
      </Sheet>
    </div>
  );
}

function SettingRow({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex items-center justify-between gap-4", disabled && "opacity-40")}>
      <span className="text-[14px] font-semibold text-ink">{label}</span>
      <span className="relative inline-flex">
        <input type="checkbox" role="switch" disabled={disabled} checked={checked && !disabled} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
        <span className="h-7 w-12 rounded-full bg-line-strong transition peer-checked:bg-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent" />
        <span className="absolute left-1 top-1 size-5 rounded-full bg-card shadow transition peer-checked:translate-x-5" />
      </span>
    </label>
  );
}

/** Suggest / translate are free — they reuse the turn's metadata (plan §6.5). */
function HintSheet({
  open,
  onClose,
  sessionId,
  lang,
  last,
  phrases,
  onUse,
  onHear,
}: {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  lang: Lang;
  last: LiveTurn | undefined;
  phrases: { text: string; meaning: string; reading?: string | null }[];
  onUse: (text: string) => void;
  onHear: (text: string) => void;
}) {
  const [tab, setTab] = useState<"suggest" | "translate" | "phrases">("suggest");
  const [translation, setTranslation] = useState<string | null>(null);
  useEffect(() => {
    if (!open || tab !== "translate" || !last) return;
    if (last.translation) return setTranslation(last.translation);
    requestHint(sessionId, { type: "translate", turn_idx: last.idx ?? undefined })
      .then((r) => setTranslation(r.translation ?? "No translation available for this line."))
      .catch(() => setTranslation("Translation is unavailable right now."));
  }, [open, tab, last, sessionId]);

  const suggestions = last?.suggested ?? [];
  return (
    <Sheet open={open} onClose={onClose} title="Hints">
      <div role="tablist" className="mb-4 grid grid-cols-3 gap-1 rounded-full bg-paper-2 p-1">
        {(["suggest", "translate", "phrases"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cx("tap rounded-full text-[13px] font-semibold capitalize transition", tab === t ? "bg-card text-ink shadow-sm" : "text-ink-3")}>
            {t === "suggest" ? "Ideas" : t}
          </button>
        ))}
      </div>
      {tab === "suggest" ? (
        suggestions.length ? (
          <ul className="space-y-2">
            {suggestions.map((text) => (
              <li key={text} className="flex items-center gap-2 rounded-2xl bg-paper-2 p-2 pl-4">
                <span lang={lang} className="target flex-1 text-[17px] text-ink">{text}</span>
                <IconButton icon="speaker" label="Hear it" onClick={() => onHear(text)} />
                <button onClick={() => onUse(text)} className="tap rounded-full bg-card px-3 text-[13px] font-semibold text-accent-ink hairline">Use</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[14px] text-ink-2">No suggestions for this line yet — try the phrases tab.</p>
        )
      ) : null}
      {tab === "translate" ? (
        <div className="rounded-2xl bg-paper-2 p-4">
          <p lang={lang} className="target text-[17px] text-ink">{last?.text}</p>
          <p className="mt-2 text-[15px] text-ink-2">{translation ?? <Spinner size={16} />}</p>
        </div>
      ) : null}
      {tab === "phrases" ? (
        <ul className="space-y-2">
          {phrases.map((p) => (
            <li key={p.text} className="flex items-center gap-2 rounded-2xl bg-paper-2 p-2 pl-4">
              <span className="flex-1">
                <span lang={lang} className="target block text-[16px] text-ink">{p.text}</span>
                <span className="block text-[12.5px] text-ink-3">{p.meaning}</span>
              </span>
              <IconButton icon="speaker" label="Hear it" onClick={() => onHear(p.text)} />
              <button onClick={() => onUse(p.text)} className="tap rounded-full bg-card px-3 text-[13px] font-semibold text-accent-ink hairline">Use</button>
            </li>
          ))}
        </ul>
      ) : null}
    </Sheet>
  );
}

/** Tap-on-word popover (plan §11.3 E): reading, meaning, save, hear. */
function WordSheet({ word, onClose, sessionId, lang, onHear }: { word: string | null; onClose: () => void; sessionId: string; lang: Lang; onHear: (t: string) => void }) {
  const [info, setInfo] = useState<Explanation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = useSaveWord();
  const { guest } = useSessionInfo();

  useEffect(() => {
    setInfo(null);
    setError(null);
    save.reset();
    if (!word) return;
    requestHint(sessionId, { type: "explain", target: word })
      .then((r) => setInfo(r.explanation ?? null))
      .catch((e) => setError(problemMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word, sessionId]);

  return (
    <Sheet open={word !== null} onClose={onClose} title="Word">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p lang={lang} className="target text-[34px] font-medium leading-tight text-ink">{word}</p>
          {info?.reading ? <p className="text-[14px] text-ink-3">{info.reading}</p> : null}
        </div>
        {word ? <IconButton icon="speaker" label="Hear it" onClick={() => onHear(word)} /> : null}
      </div>
      {error ? <ErrorBanner className="mt-4" message={error} /> : null}
      {!info && !error ? <div className="mt-4 flex items-center gap-2 text-ink-3"><Spinner size={16} /> Looking it up…</div> : null}
      {info ? (
        <div className="fade-in mt-4 space-y-3">
          <p className="text-[17px] text-ink">{info.meaning}</p>
          {info.part_of_speech ? <p className="text-[12px] uppercase tracking-wide text-ink-3">{info.part_of_speech}</p> : null}
          {info.example ? (
            <div className="rounded-2xl bg-paper-2 p-3">
              <p lang={lang} className="target text-[16px] text-ink">{info.example}</p>
              {info.example_translation ? <p className="mt-1 text-[13px] text-ink-2">{info.example_translation}</p> : null}
            </div>
          ) : null}
          {info.note ? <p className="text-[13px] text-improve">{info.note}</p> : null}
          {guest ? (
            <p className="text-[13px] text-ink-3"><Link className="font-medium text-accent-ink underline-offset-4 hover:underline" href="/settings#account">Create an account</Link> to save words as flashcards.</p>
          ) : (
            <Button
              variant={save.isSuccess ? "quiet" : "secondary"}
              icon={save.isSuccess ? "check" : "bookmark"}
              disabled={save.isPending || save.isSuccess}
              onClick={() => word && save.mutate({ language: lang, term: word, meaning: info.meaning, reading: info.reading ?? null, example: info.example ?? null, source_session_id: sessionId })}
            >
              {save.isSuccess ? "Saved to flashcards" : "Save to flashcards"}
            </Button>
          )}
        </div>
      ) : null}
    </Sheet>
  );
}
