"use client";

import type { Lang } from "@talkscene/sdk";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { TopBar } from "@/components/AppShell";
import { GoalChecklist } from "@/components/Conversation";
import { ErrorBanner, LevelBadge } from "@/components/feedback";
import { Icon } from "@/components/Icon";
import { Button, Display, Eyebrow, Skeleton } from "@/components/ui";
import { problemMessage, useMe, useScenario, useStartSession } from "@/lib/api";
import { speak } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { applyLang, LANGS } from "@/lib/lang";
import { useLive } from "@/lib/store/session";
import { usePrefs } from "@/lib/store/prefs";

/** The register each scene expects of the learner, named the way learners know it. */
const REGISTER_FORM: Partial<Record<Lang, Record<"casual" | "polite" | "formal", string>>> = {
  ko: { casual: "반말", polite: "해요체", formal: "합쇼체" },
  ja: { casual: "plain form", polite: "です/ます", formal: "敬語" },
  de: { casual: "du", polite: "Sie", formal: "Sie" },
};
const REGISTER_HINT = {
  casual: "Casually, as with a friend",
  polite: "Politely",
  formal: "Formally — the report checks this",
} as const;

export default function ScenarioBrief() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: s, isLoading, error } = useScenario(id);
  const me = useMe();
  const start = useStartSession();
  const prefs = usePrefs();

  const [length, setLength] = useState<"short" | "standard" | "long">("standard");
  const [input, setInput] = useState<"voice" | "text">("voice");
  const [hints, setHints] = useState(true);
  const [premium, setPremium] = useState(false);

  // The brief wears the scenario's language before the conversation does.
  useEffect(() => {
    if (s) applyLang(s.language as Lang);
    return () => applyLang(usePrefs.getState().lang);
  }, [s]);
  useEffect(() => {
    if (me.data) setPremium(me.data.prefs.tts_provider === "premium");
  }, [me.data]);

  if (isLoading || !s) {
    return (
      <>
        <TopBar back="/scenarios" />
        <div className="mx-auto max-w-3xl space-y-4 px-5 pt-8">
          {error ? <ErrorBanner message={problemMessage(error)} /> : <><Skeleton className="h-10 w-2/3" /><Skeleton className="h-40" /><Skeleton className="h-56" /></>}
        </div>
      </>
    );
  }

  const lang = s.language as Lang;
  const turns = { short: s.turn_limits.min, standard: s.turn_limits.default, long: s.turn_limits.max };
  const targetTitle = lang !== "en" ? s.title[lang] : undefined;

  const begin = async () => {
    const response = await start.mutateAsync({
      scenario_id: s.id,
      target_turns: turns[length],
      options: {
        input,
        hints,
        show_translation: true,
        romanization: true,
        furigana: true,
        tts_tier: premium ? "premium" : "standard",
        tts_rate: prefs.level === "A1" ? 0.85 : 1,
      },
    });
    useLive.getState().hydrate(response);
    router.push(`/session/${response.session_id}`);
  };

  return (
    <div className="glow-accent min-h-dvh">
      <TopBar back="/scenarios" title={s.title.en} subtitle={`${LANGS[lang].name} · ${s.level}`} />
      <div className="mx-auto max-w-3xl px-5 pb-36 pt-8">
        <div className="reveal flex items-start gap-4">
          <span className="emoji grid size-16 shrink-0 place-items-center rounded-[22px] bg-card text-4xl hairline" aria-hidden>
            {s.icon ?? "💬"}
          </span>
          <div className="min-w-0">
            {targetTitle ? <p lang={lang} className="target text-[15px] text-accent-ink">{targetTitle}</p> : null}
            <Display className="text-[32px] leading-tight">{s.title.en}</Display>
            <div className="mt-2 flex items-center gap-2 text-[13px] text-ink-3">
              <LevelBadge level={s.level} />
              <span className="inline-flex items-center gap-1"><Icon name="clock" size={14} /> ~{s.estimated_minutes} min</span>
              {s.completed ? <span className="inline-flex items-center gap-1 text-great"><Icon name="check" size={14} /> Best {s.best_score}</span> : null}
            </div>
          </div>
        </div>

        <p className="reveal mt-5 text-[16px] leading-relaxed text-ink-2 pretty" style={{ ["--i" as string]: 1 }}>{s.summary}</p>

        <section className="card reveal mt-6 divide-y divide-line" style={{ ["--i" as string]: 2 }}>
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <div>
              <Eyebrow>You are</Eyebrow>
              <p className="mt-1 text-[15px] text-ink pretty">{s.user_role}</p>
            </div>
            <div>
              <Eyebrow>You’ll talk to</Eyebrow>
              <p className="mt-1 text-[15px] text-ink">
                <span lang={lang} className="target font-semibold">{s.persona.name}</span>, {s.persona.role.toLowerCase()}
              </p>
              <p className="mt-0.5 text-[13px] text-ink-3">{s.setting}</p>
            </div>
            {s.learner_register ? (
              <div className="sm:col-span-2">
                <Eyebrow>Speak</Eyebrow>
                <p className="mt-1 text-[15px] text-ink">
                  {REGISTER_HINT[s.learner_register]}{" "}
                  <span lang={lang} className="target font-medium text-accent-ink">({REGISTER_FORM[lang]?.[s.learner_register]})</span>
                </p>
              </div>
            ) : null}
          </div>
          <div className="p-5">
            <Eyebrow>Your goals</Eyebrow>
            <GoalChecklist className="mt-3" goals={s.goals.map((g) => ({ ...g, done: false, turn_completed: null }))} />
            <p className="mt-3 text-[12.5px] text-ink-3">The character will not read these out — they come up naturally if you steer.</p>
          </div>
        </section>

        {s.useful_phrases.length ? (
          <section className="reveal mt-6" style={{ ["--i" as string]: 3 }} aria-labelledby="phrases">
            <h2 id="phrases" className="font-display text-[22px] text-ink">Useful phrases</h2>
            <p className="text-[13px] text-ink-3">Tap to hear.</p>
            <ul className="mt-3 space-y-2">
              {s.useful_phrases.map((p) => (
                <li key={p.text}>
                  <button
                    onClick={() => void speak(p.text, lang, prefs.level === "A1" ? 0.85 : 1, s.voice?.browser_hint)}
                    className="group flex w-full items-start gap-3 rounded-2xl bg-card p-4 text-left transition hairline hover:bg-paper-2"
                  >
                    <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-ink transition group-hover:scale-105">
                      <Icon name="speaker" size={16} />
                    </span>
                    <span className="min-w-0">
                      <span lang={lang} className="target block text-[18px] text-ink">{p.text}</span>
                      {p.reading ? <span className="block text-[12.5px] italic text-ink-3">{p.reading}</span> : null}
                      <span className="mt-0.5 block text-[14px] text-ink-2">{p.meaning}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {s.cultural_notes.length ? (
          <section className="reveal mt-6 rounded-[18px] bg-accent-soft/60 p-5" style={{ ["--i" as string]: 4 }}>
            <p className="flex items-center gap-2 text-[13px] font-semibold text-accent-ink"><Icon name="sparkle" size={16} /> Good to know</p>
            <ul className="mt-2 space-y-2 text-[14.5px] leading-relaxed text-ink-2">
              {s.cultural_notes.map((n) => <li key={n} className="pretty">{n}</li>)}
            </ul>
          </section>
        ) : null}

        <section className="card reveal mt-6 space-y-5 p-5" style={{ ["--i" as string]: 5 }} aria-label="Conversation settings">
          <fieldset>
            <legend className="text-[14px] font-semibold text-ink">Conversation length</legend>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {(["short", "standard", "long"] as const).map((key) => (
                <label key={key} className={cx("tap flex cursor-pointer flex-col items-center justify-center rounded-2xl py-2.5 text-center transition", length === key ? "bg-ink text-paper" : "bg-paper-2 text-ink-2 hover:text-ink")}>
                  <input type="radio" name="length" className="sr-only" checked={length === key} onChange={() => setLength(key)} />
                  <span className="text-[14px] font-semibold capitalize">{key}</span>
                  <span className="text-[12px] opacity-75">{turns[key]} turns</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-[14px] font-semibold text-ink">Reply by</legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {([["voice", "mic", "Voice"], ["text", "keyboard", "Typing"]] as const).map(([key, icon, label]) => (
                <label key={key} className={cx("tap flex cursor-pointer items-center justify-center gap-2 rounded-2xl py-3 text-[14px] font-semibold transition", input === key ? "bg-ink text-paper" : "bg-paper-2 text-ink-2 hover:text-ink")}>
                  <input type="radio" name="input" className="sr-only" checked={input === key} onChange={() => setInput(key)} />
                  <Icon name={icon} size={18} /> {label}
                </label>
              ))}
            </div>
            <p className="mt-1.5 text-[12px] text-ink-3">You can switch any time during the conversation.</p>
          </fieldset>

          <div className="space-y-3">
            <Toggle label="Hints" description="Suggested replies and translations when you get stuck." checked={hints} onChange={setHints} />
            <Toggle label="Premium voice" description="Natural neural voice. Uses your monthly allowance; the browser voice is unlimited." checked={premium} onChange={setPremium} />
          </div>
        </section>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper/90 px-5 pb-5 pt-3 backdrop-blur-xl safe-bottom">
        <div className="mx-auto max-w-3xl">
          {start.error ? <ErrorBanner className="mb-3" message={problemMessage(start.error)} /> : null}
          <Button size="lg" className="w-full" onClick={begin} disabled={start.isPending} iconRight="arrow">
            {start.isPending ? "Setting the scene…" : "Start conversation"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Toggle({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <span>
        <span className="block text-[14px] font-semibold text-ink">{label}</span>
        <span className="block text-[12.5px] text-ink-3 pretty">{description}</span>
      </span>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
        <span className="h-7 w-12 rounded-full bg-line-strong transition peer-checked:bg-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent" />
        <span className="absolute left-1 top-1 size-5 rounded-full bg-card shadow transition peer-checked:translate-x-5" />
      </span>
    </label>
  );
}
