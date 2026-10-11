"use client";

import type { DrillAttempt, Lang } from "@talkscene/sdk";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { TopBar } from "@/components/AppShell";
import { BandBadge, EmptyState, ErrorBanner } from "@/components/feedback";
import { Icon } from "@/components/Icon";
import { PhonemeStrip } from "@/components/learning";
import { WaveformMeter } from "@/components/MicButton";
import { Button, Display, Skeleton } from "@/components/ui";
import { client, problemMessage, useDrillSet, useStatus } from "@/lib/api";
import { MicPermissionError, Recorder } from "@/lib/audio/recorder";
import { speak } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { applyLang } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

const MAX_SECONDS = 15;

export default function Drills() {
  const { id } = useParams<{ id: string }>();
  const set = useDrillSet(id);
  const status = useStatus();
  const [index, setIndex] = useState(0);
  const [attempts, setAttempts] = useState<Record<string, DrillAttempt[]>>({});
  const [state, setState] = useState<"idle" | "recording" | "scoring">("idle");
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<Recorder | null>(null);
  const levelRef = useRef(0);
  const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const drills = set.data?.drills ?? [];
  const drill = drills[index];
  const lang = (drill?.language ?? "en") as Lang;
  const serverVoice = Boolean(status.data?.live_providers?.tts?.length);

  useEffect(() => {
    if (drill) applyLang(lang);
    return () => applyLang(usePrefs.getState().lang);
  }, [drill, lang]);
  useEffect(() => () => recorder.current?.close(), []);

  const playNative = async (rate = 1) => {
    if (!drill) return;
    if (serverVoice) {
      const url = await client.fetchAudio(`/v1/drills/${drill.id}/reference-audio?rate=${rate}`);
      if (url) {
        const audio = new Audio(url);
        audio.playbackRate = 1;
        void audio.play();
        return;
      }
    }
    void speak(drill.ref_text, lang, rate * 0.95);
  };

  const record = async () => {
    setError(null);
    try {
      recorder.current ??= await Recorder.open();
    } catch (e) {
      setError(e instanceof MicPermissionError ? e.message : "The microphone could not start.");
      return;
    }
    setState("recording");
    await recorder.current.start({ onLevel: (l) => (levelRef.current = l) });
    stopTimer.current = setTimeout(() => void finish(), MAX_SECONDS * 1000);
  };

  const finish = async () => {
    if (stopTimer.current) clearTimeout(stopTimer.current);
    if (!recorder.current || !drill) return;
    setState("scoring");
    const result = await recorder.current.stop();
    levelRef.current = 0;
    if (!result.voiced) {
      setState("idle");
      setError("That was silent — hold the phone a little closer and try again.");
      return;
    }
    try {
      const attempt = await client.submitDrillAttempt(drill.id, result.blob);
      setAttempts((prev) => ({ ...prev, [drill.id]: [...(prev[drill.id] ?? drill.attempts ?? []), attempt] }));
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setState("idle");
    }
  };

  if (set.isLoading) {
    return (
      <>
        <TopBar back={`/session/${id}/report`} title="Shadowing drills" />
        <div className="mx-auto max-w-xl space-y-4 px-5 pt-8"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-64" /></div>
      </>
    );
  }
  if (set.error || !drill) {
    return (
      <>
        <TopBar back={`/session/${id}/report`} title="Shadowing drills" />
        <div className="mx-auto max-w-xl px-5 pt-8">
          {set.error ? <ErrorBanner message={problemMessage(set.error)} onRetry={() => void set.refetch()} /> : <EmptyState title="No drills for this session" body="Speak a session out loud and the report will pick sentences to practise." action={{ label: "Back to report", href: `/session/${id}/report` }} />}
        </div>
      </>
    );
  }

  const history = attempts[drill.id] ?? drill.attempts ?? [];
  const latest = history[history.length - 1];
  const best = history.reduce<number | null>((b, a) => (a.accuracy != null && (b == null || a.accuracy > b) ? a.accuracy : b), drill.best_accuracy ?? null);
  const quota = set.data?.quota;

  return (
    <div className="glow-accent min-h-dvh">
      <TopBar back={`/session/${id}/report`} title="Shadowing drills" subtitle={`${index + 1} of ${drills.length}`} />
      <div className="mx-auto max-w-xl px-5 pb-16 pt-6">
        <ol className="flex gap-1.5" aria-label="Drills">
          {drills.map((d, i) => (
            <li key={d.id} className="flex-1">
              <button onClick={() => setIndex(i)} aria-current={i === index ? "step" : undefined} aria-label={`Drill ${i + 1}`} className={cx("tap block w-full", "after:block after:h-1.5 after:rounded-full after:transition", i === index ? "after:bg-accent" : (attempts[d.id]?.length || d.attempts?.length) ? "after:bg-accent/45" : "after:bg-line-strong")} />
            </li>
          ))}
        </ol>

        <div key={drill.id} className="reveal mt-8 text-center">
          <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-3">Listen · Repeat · Compare</p>
          <p lang={lang} className="target mt-4 text-[34px] font-medium leading-snug text-ink balance">
            {drill.ref_text}
          </p>
          {drill.translation_en ? <p className="mt-2 text-[15px] text-ink-2">{drill.translation_en}</p> : null}
          {drill.focus_words.length ? (
            <p className="mt-3 text-[13px] text-ink-3">
              Focus: <span lang={lang} className="target font-medium text-accent-ink">{drill.focus_words.join(", ")}</span>
            </p>
          ) : null}
        </div>

        <div className="mt-8 flex justify-center gap-2">
          <Button variant="secondary" icon="speaker" onClick={() => void playNative(1)}>Listen</Button>
          <Button variant="ghost" icon="turtle" onClick={() => void playNative(0.75)}>Slowly</Button>
        </div>

        <div className="card mt-8 p-6">
          <WaveformMeter levelRef={levelRef} active={state === "recording"} />
          <div className="mt-4 flex justify-center">
            {state === "recording" ? (
              <Button icon="stop" onClick={() => void finish()}>Stop and score</Button>
            ) : (
              <Button icon="mic" onClick={() => void record()} disabled={state === "scoring"}>
                {state === "scoring" ? "Scoring…" : latest ? "Try again" : "Record yourself"}
              </Button>
            )}
          </div>
          {error ? <ErrorBanner className="mt-4" message={error} /> : null}
        </div>

        {latest ? (
          <section className="reveal mt-6 space-y-5" aria-live="polite">
            <div className="flex items-center justify-between">
              <Display as="h2" className="text-[24px]">Attempt {latest.attempt}</Display>
              {best != null ? <span className="text-[13px] text-ink-2">Best: <span className="font-semibold text-ink">{Math.round(best)}</span></span> : null}
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {([["Accuracy", latest.accuracy], ["Fluency", latest.fluency], ["Completeness", latest.completeness], ["Prosody", latest.prosody]] as const).map(([label, value]) => (
                <div key={label} className="card p-3 text-center">
                  <p className="text-[12px] text-ink-3">{label}</p>
                  <p className="mt-1 text-[26px] font-semibold leading-none text-ink">{value == null ? "—" : Math.round(value)}</p>
                  <div className="mt-2 flex justify-center">{value == null ? <span className="text-[11px] text-ink-3">not available</span> : <BandBadge score={value} />}</div>
                </div>
              ))}
            </div>
            {!latest.authoritative ? (
              <p className="flex items-start gap-1.5 rounded-2xl bg-improve-soft p-3 text-[13px] text-improve">
                <Icon name="info" size={15} className="mt-0.5 shrink-0" />
                Estimated scores. {quota?.note || "Phoneme-level pronunciation assessment is not configured on this server."}
              </p>
            ) : null}
            <div className="card p-5">
              <PhonemeStrip attempt={latest} lang={lang} />
            </div>
            <div className="flex flex-wrap gap-2">
              {latest.audio_url ? (
                <Button variant="secondary" size="sm" icon="play" onClick={async () => {
                  const url = await client.fetchAudio(latest.audio_url!);
                  if (url) void new Audio(url).play();
                }}>Listen to yours</Button>
              ) : null}
              <Button variant="secondary" size="sm" icon="speaker" onClick={() => void playNative(1)}>Listen to the model</Button>
              {index < drills.length - 1 ? (
                <Button size="sm" iconRight="forward" onClick={() => setIndex(index + 1)} className="ml-auto">Next</Button>
              ) : (
                <Link href={`/session/${id}/report`} className="tap ml-auto inline-flex h-10 items-center rounded-full bg-accent px-4 text-sm font-medium text-on-accent">Done</Link>
              )}
            </div>
          </section>
        ) : null}

        {quota && quota.seconds_limit ? (
          <p className="mt-10 text-center text-[12px] text-ink-3">
            Pronunciation scoring this month: {quota.seconds_used_this_month}s of {quota.seconds_limit}s
          </p>
        ) : null}
      </div>
    </div>
  );
}
