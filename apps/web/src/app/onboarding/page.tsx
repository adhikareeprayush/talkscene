"use client";

import type { Lang, Level } from "@talkscene/sdk";
import { useSessionInfo } from "@/lib/client-state";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { LanguagePicker } from "@/components/catalog";
import { Icon } from "@/components/Icon";
import { WaveformMeter } from "@/components/MicButton";
import { Button, Display, Eyebrow } from "@/components/ui";
import { api, ensureSession, useLanguages } from "@/lib/api";
import { MicPermissionError, Recorder, recordingSupported } from "@/lib/audio/recorder";
import { recognitionSupported, speak, synthesisSupported } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { LANGS, LEVELS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

const GOALS = [
  { id: "travel", label: "Travel", icon: "✈️" },
  { id: "work", label: "Work", icon: "💼" },
  { id: "daily", label: "Daily life", icon: "🏠" },
  { id: "exams", label: "Exams", icon: "📝" },
  { id: "culture", label: "Friends & culture", icon: "🎎" },
];

const STEPS = ["Language", "Level", "Goals", "Sound check"] as const;

export default function Onboarding() {
  const router = useRouter();
  const prefs = usePrefs();
  const { data: languages } = useLanguages();
  const [step, setStep] = useState(0);
  const [lang, setLang] = useState<Lang | null>(prefs.lang);
  const [level, setLevel] = useState<Level>(prefs.level);
  const [goals, setGoals] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const counts = Object.fromEntries((languages ?? []).map((l) => [l.code, l.scenario_count]));

  const finish = async () => {
    setSaving(true);
    try {
      await ensureSession("en");
      await api.PATCH("/v1/me", {
        body: { target_lang: lang ?? undefined, level, goals, daily_goal_minutes: prefs.dailyGoal } as never,
      });
    } catch {
      /* the device-level prefs below are enough to continue */
    }
    prefs.set({ lang, level, onboarded: true });
    router.push("/home");
  };

  const canNext = step === 0 ? lang !== null : true;

  return (
    <div className="glow-accent min-h-dvh">
      <div className="mx-auto flex min-h-dvh max-w-xl flex-col px-6 pb-8 pt-6">
        <div className="flex items-center justify-between">
          <button
            onClick={() => (step ? setStep(step - 1) : router.push("/"))}
            className="tap grid place-items-center rounded-full text-ink-2 hover:bg-paper-2"
            aria-label="Back"
          >
            <Icon name="back" size={22} />
          </button>
          <ol className="flex gap-1.5" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            {STEPS.map((name, i) => (
              <li key={name} className={cx("h-1.5 rounded-full transition-all duration-500", i <= step ? "w-8 bg-accent" : "w-4 bg-line-strong")}>
                <span className="sr-only">{name}{i === step ? " (current)" : ""}</span>
              </li>
            ))}
          </ol>
          <button onClick={finish} className="tap rounded-full px-3 text-sm font-medium text-ink-3 hover:text-ink">
            Skip
          </button>
        </div>

        <div key={step} className="flex-1 pt-10">
          {step === 0 ? (
            <>
              <Eyebrow className="reveal">Step 1</Eyebrow>
              <Display className="reveal mt-2 text-[34px] leading-tight" >What do you want to speak?</Display>
              <div className="mt-8">
                <LanguagePicker
                  value={lang}
                  counts={counts}
                  onChange={(code) => {
                    setLang(code);
                    usePrefs.getState().set({ lang: code });
                  }}
                />
              </div>
            </>
          ) : null}

          {step === 1 ? (
            <>
              <Eyebrow className="reveal">Step 2</Eyebrow>
              <Display className="reveal mt-2 text-[34px] leading-tight">How much {lang ? LANGS[lang].name : "of it"} do you know?</Display>
              <div role="radiogroup" aria-label="Your level" className="mt-8 space-y-3">
                {LEVELS.map((item, i) => (
                  <button
                    key={item.level}
                    role="radio"
                    aria-checked={level === item.level}
                    onClick={() => setLevel(item.level)}
                    style={{ ["--i" as string]: i }}
                    className={cx(
                      "reveal flex w-full items-center gap-4 rounded-[20px] p-4 text-left transition",
                      level === item.level ? "bg-accent-soft ring-2 ring-accent" : "bg-card hairline hover:bg-paper-2",
                    )}
                  >
                    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-paper font-mono text-sm font-semibold text-accent-ink">{item.level}</span>
                    <span>
                      <span className="block text-[16px] font-semibold text-ink">{item.plain}</span>
                      <span className="block text-[13.5px] text-ink-2">{item.detail}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <Eyebrow className="reveal">Step 3</Eyebrow>
              <Display className="reveal mt-2 text-[34px] leading-tight">What are you practising for?</Display>
              <p className="reveal mt-2 text-ink-2">Pick any. We use this to recommend scenes.</p>
              <div className="mt-8 flex flex-wrap gap-2.5">
                {GOALS.map((goal, i) => {
                  const on = goals.includes(goal.id);
                  return (
                    <button
                      key={goal.id}
                      aria-pressed={on}
                      onClick={() => setGoals(on ? goals.filter((g) => g !== goal.id) : [...goals, goal.id])}
                      style={{ ["--i" as string]: i }}
                      className={cx(
                        "reveal tap inline-flex items-center gap-2 rounded-full px-5 py-3 text-[15px] font-medium transition",
                        on ? "bg-ink text-paper" : "bg-card text-ink hairline hover:bg-paper-2",
                      )}
                    >
                      <span aria-hidden>{goal.icon}</span>
                      {goal.label}
                      {on ? <Icon name="check" size={16} /> : null}
                    </button>
                  );
                })}
              </div>
            </>
          ) : null}

          {step === 3 ? <SoundCheck lang={lang ?? "en"} /> : null}
        </div>

        <div className="pt-6">
          {step < STEPS.length - 1 ? (
            <Button size="lg" className="w-full" disabled={!canNext} onClick={() => setStep(step + 1)} iconRight="arrow">
              Continue
            </Button>
          ) : (
            <Button size="lg" className="w-full" disabled={saving} onClick={finish} iconRight="arrow">
              {saving ? "Setting up…" : "Start practising"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Step 4 (plan §11.3 A): record 3 s, see it, hear it back, and see what this browser supports. */
function SoundCheck({ lang }: { lang: Lang }) {
  const levelRef = useRef(0);
  const recorder = useRef<Recorder | null>(null);
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const [clipUrl, setClipUrl] = useState<string | null>(null);
  const [voiced, setVoiced] = useState<boolean | null>(null);
  const [caps, setCaps] = useState({ mic: false, captions: false, voice: false });
  const { signedIn } = useSessionInfo();

  useEffect(() => {
    setCaps({ mic: recordingSupported(), captions: recognitionSupported(), voice: synthesisSupported() });
    return () => {
      recorder.current?.close();
      if (clipUrl) URL.revokeObjectURL(clipUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const record = async () => {
    setError(null);
    try {
      recorder.current ??= await Recorder.open();
      setState("recording");
      await recorder.current.start({ onLevel: (l) => (levelRef.current = l) });
      setTimeout(async () => {
        const result = await recorder.current!.stop();
        levelRef.current = 0;
        setVoiced(result.voiced);
        setClipUrl(URL.createObjectURL(result.blob));
        setState("done");
      }, 3000);
    } catch (e) {
      setState("idle");
      setError(e instanceof MicPermissionError ? e.message : "The microphone could not start.");
    }
  };

  const capabilities = [
    { ok: caps.mic, label: "Microphone recording" },
    { ok: caps.captions, label: "Live captions", note: caps.captions ? undefined : "Not in this browser — your speech is still transcribed on our server." },
    { ok: caps.voice, label: `Built-in ${LANGS[lang].name} voice`, note: caps.voice ? undefined : "Premium voices still work." },
  ];

  return (
    <>
      <Eyebrow className="reveal">Step 4</Eyebrow>
      <Display className="reveal mt-2 text-[34px] leading-tight">Quick sound check</Display>
      <p className="reveal mt-2 text-ink-2">Say anything for three seconds — your name is fine.</p>

      <div className="card reveal mt-8 p-6" style={{ ["--i" as string]: 1 }}>
        <WaveformMeter levelRef={levelRef} active={state === "recording"} />
        <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
          <Button onClick={record} disabled={state === "recording" || !caps.mic} icon="mic" variant={state === "done" ? "secondary" : "primary"}>
            {state === "recording" ? "Listening…" : state === "done" ? "Record again" : "Record 3 seconds"}
          </Button>
          {clipUrl ? (
            <Button variant="secondary" icon="play" onClick={() => void new Audio(clipUrl).play()}>
              Play it back
            </Button>
          ) : null}
          {caps.voice ? (
            <Button variant="ghost" icon="speaker" onClick={() => void speak(LANGS[lang].hello, lang)}>
              Test voice
            </Button>
          ) : null}
        </div>
        {voiced === false ? (
          <p className="mt-4 text-center text-[13px] text-improve">That was very quiet — check the mic is not muted, or move closer.</p>
        ) : voiced ? (
          <p className="mt-4 text-center text-[13px] text-great">Sounds good.</p>
        ) : null}
        {error ? <p className="mt-4 text-center text-[13px] text-attention">{error}</p> : null}
      </div>

      <ul className="reveal mt-6 space-y-2.5" style={{ ["--i" as string]: 2 }}>
        {capabilities.map((c) => (
          <li key={c.label} className="flex items-start gap-3 text-[14px]">
            <span className={cx("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full", c.ok ? "bg-great text-paper" : "bg-paper-2 text-ink-3")}>
              <Icon name={c.ok ? "check" : "x"} size={12} strokeWidth={2.5} />
            </span>
            <span>
              <span className="text-ink">{c.label}</span>
              {c.note ? <span className="block text-[12.5px] text-ink-3">{c.note}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-5 text-[12px] text-ink-3">
        {signedIn ? "" : "You'll start as a guest — sign up any time to keep your history across devices."}
      </p>
    </>
  );
}
