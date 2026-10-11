"use client";

import type { Lang, Report } from "@talkscene/sdk";
import Link from "next/link";
import { useSessionInfo } from "@/lib/client-state";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { TopBar } from "@/components/AppShell";
import { ScoreMeter, SkillBars, type SkillRow } from "@/components/charts";
import { GoalChecklist } from "@/components/Conversation";
import { BandBadge, EmptyState, ErrorBanner, LevelBadge } from "@/components/feedback";
import { Icon } from "@/components/Icon";
import { CorrectionCard } from "@/components/learning";
import { Display, Eyebrow, LinkButton, Skeleton } from "@/components/ui";
import { problemMessage, useReport, useSaveWord, useScenario } from "@/lib/api";
import { speak } from "@/lib/audio/speech";
import { cx, plural, seconds } from "@/lib/format";
import { applyLang, LANGS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

const TABS = ["Overview", "Speaking", "Grammar", "Vocab", "Pronunciation", "Transcript"] as const;
type Tab = (typeof TABS)[number];

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, refetch } = useReport(id);
  const report = data?.status === "ready" ? data.report : null;
  const scenario = useScenario(report?.scenario_id ?? "");
  const next = useScenario(report?.next_steps.next_scenario_id ?? "");
  const [tab, setTab] = useState<Tab>("Overview");

  useEffect(() => {
    if (report) applyLang(report.language as Lang);
    return () => applyLang(usePrefs.getState().lang);
  }, [report]);

  if (error) {
    return (
      <>
        <TopBar back="/history" title="Feedback" />
        <div className="mx-auto max-w-3xl px-5 pt-8">
          <ErrorBanner message={problemMessage(error)} onRetry={() => void refetch()} />
        </div>
      </>
    );
  }

  if (!report) return <Analyzing eta={data?.status === "analyzing" ? data.eta : 8} />;

  const lang = report.language as Lang;
  const title = scenario.data?.title.en ?? "Your conversation";

  return (
    <div className="min-h-dvh">
      <TopBar back="/history" title={title} subtitle={`${LANGS[lang].name} · ${report.level}`} />
      <div className="glow-accent">
        <div className="mx-auto max-w-3xl px-5 pb-10 pt-8">
          <p className="reveal text-center text-[13px] font-medium text-ink-3">
            Session complete <span className="emoji" aria-hidden>🎉</span>
          </p>
          <div className="reveal mt-4 flex flex-col items-center gap-6 sm:flex-row sm:justify-center sm:gap-10" style={{ ["--i" as string]: 1 }}>
            <ScoreMeter value={report.overall} />
            <div className="text-center sm:text-left">
              <Eyebrow>Estimated level this session</Eyebrow>
              <p className="mt-1 font-display text-[44px] leading-none text-ink">≈ {report.estimated_cefr}</p>
              <div className="mt-3 flex items-center justify-center gap-2 sm:justify-start">
                <BandBadge score={report.overall} />
                <span className="text-[13px] text-ink-2">
                  {report.goals.done}/{report.goals.total} goals
                </span>
              </div>
            </div>
          </div>
          <p className="reveal mx-auto mt-6 max-w-xl text-center text-[16px] leading-relaxed text-ink-2 pretty" style={{ ["--i" as string]: 2 }}>
            {report.summary}
          </p>
        </div>
      </div>

      <nav className="sticky top-14 z-10 border-b border-line bg-paper/95 backdrop-blur-xl" aria-label="Report sections">
        <div role="tablist" className="mx-auto flex max-w-3xl gap-1 overflow-x-auto px-3 scrollbar-none">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx(
                "tap relative shrink-0 px-3 text-[14px] font-medium transition",
                "after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full",
                tab === t ? "text-ink after:bg-accent" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {t}
              {t === "Pronunciation" ? <span className="ml-1 text-[11px] text-ink-3">(est.)</span> : null}
            </button>
          ))}
        </div>
      </nav>

      <div key={tab} className="mx-auto max-w-3xl px-5 pb-44 pt-6 md:pb-6">
        {tab === "Overview" ? <Overview report={report} /> : null}
        {tab === "Speaking" ? <Speaking report={report} /> : null}
        {tab === "Grammar" ? <Grammar report={report} lang={lang} /> : null}
        {tab === "Vocab" ? <Vocab report={report} lang={lang} /> : null}
        {tab === "Pronunciation" ? <Pronunciation report={report} lang={lang} /> : null}
        {tab === "Transcript" ? <Transcript report={report} lang={lang} /> : null}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper/90 px-5 py-3 backdrop-blur-xl safe-bottom md:bottom-auto md:static md:border-0 md:bg-transparent">
        {/* Phones: the primary action gets its own full-width row. */}
        <div className="mx-auto grid max-w-3xl grid-cols-2 gap-2 md:flex md:pb-10">
          {report.pronunciation.drills.length ? (
            <LinkButton href={`/session/${id}/drills`} icon="mic" className="col-span-2 md:flex-1">
              Practise weak words
            </LinkButton>
          ) : null}
          <LinkButton href={`/scenarios/${report.next_steps.retry_scenario_id}`} variant="secondary" icon="retry" className="md:flex-1">
            Retry
          </LinkButton>
          {report.next_steps.next_scenario_id ? (
            <LinkButton href={`/scenarios/${report.next_steps.next_scenario_id}`} variant="secondary" iconRight="forward" className="md:flex-1">
              {next.data ? `Next: ${next.data.title.en}` : "Next scene"}
            </LinkButton>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Analyzing({ eta }: { eta: number }) {
  return (
    <div className="glow-accent grid min-h-dvh place-items-center px-6">
      <div className="w-full max-w-md text-center" role="status" aria-live="polite">
        <div className="relative mx-auto size-24">
          <span className="absolute inset-0 rounded-full bg-accent/20" style={{ animation: "breathe 1.8s ease-in-out infinite" }} />
          <span className="absolute inset-4 grid place-items-center rounded-full bg-accent text-on-accent">
            <Icon name="sparkle" size={28} />
          </span>
        </div>
        <Display className="mt-8 text-[30px]">Analysing your conversation…</Display>
        <p className="mt-2 text-ink-2">Checking goals, grammar, fluency and pronunciation — usually {Math.max(4, eta)} to 10 seconds.</p>
        <div className="mt-8 space-y-3">
          <Skeleton className="h-6" />
          <Skeleton className="h-6 w-4/5" />
          <Skeleton className="h-6 w-3/5" />
        </div>
      </div>
    </div>
  );
}

function skillRows(report: Report): SkillRow[] {
  const s = report.scores;
  const sp = report.speaking;
  const cjk = report.language === "ko" || report.language === "ja";
  const rate = cjk ? `${Math.round(sp.chars_per_minute)} characters/min` : `${Math.round(sp.words_per_minute)} words/min`;
  const excluded = new Set(s.excluded_from_overall);
  const hits = report.vocabulary.target_hit_rate;
  return [
    {
      key: "task",
      label: "Task completion",
      value: s.task_completion,
      weight: s.weights.task_completion ?? 0.3,
      explanation: `You completed ${report.goals.done} of ${report.goals.total} goals.`,
    },
    {
      key: "grammar",
      label: "Grammar & accuracy",
      value: s.grammar,
      weight: s.weights.grammar ?? 0.25,
      explanation: report.grammar.corrections.length
        ? `${plural(report.grammar.corrections.length, "thing")} to polish — see the Grammar tab.`
        : report.grammar.note ?? "No significant errors spotted.",
    },
    {
      key: "fluency",
      label: "Fluency",
      value: s.fluency,
      weight: s.weights.fluency ?? 0.2,
      explanation: sp.estimated_from_text
        ? "Typed session — pace is not measured, so this reflects turn length only."
        : `${sp.rate_label === "unknown" ? "Pace unclear" : `${sp.rate_label[0]!.toUpperCase()}${sp.rate_label.slice(1)} pace`} (${rate}), ${plural(sp.long_pauses.length, "long pause")}, ${plural(sp.filler_total, "filler")}.`,
    },
    {
      key: "pronunciation",
      label: "Pronunciation (estimated)",
      value: s.pronunciation ?? null,
      weight: s.weights.pronunciation ?? 0.15,
      excluded: excluded.has("pronunciation"),
      explanation:
        s.pronunciation == null
          ? "Not measured — this session had no audio. The overall score is weighted without it."
          : `An estimate from speech recognition: ${plural(report.pronunciation.unclear_words.length, "word")} may have been unclear. Drills give a real score.`,
    },
    {
      key: "vocab",
      label: "Vocabulary range",
      value: s.vocabulary,
      weight: s.weights.vocabulary ?? 0.1,
      explanation:
        hits.rate != null
          ? `You used ${hits.used.length} of ${hits.used.length + hits.missed.length} target words.`
          : "Based on the range of words you used.",
    },
  ];
}

function Overview({ report }: { report: Report }) {
  const rows = useMemo(() => skillRows(report), [report]);
  return (
    <div className="space-y-6">
      <section className="card reveal p-5">
        <h2 className="text-[15px] font-semibold text-ink">How the score is made</h2>
        <p className="mt-1 text-[13px] text-ink-3">Each part is weighted; nothing here is a guess dressed up as a number.</p>
        <div className="mt-5">
          <SkillBars rows={rows} overall={report.overall} />
        </div>
      </section>
      <section className="card reveal p-5" style={{ ["--i" as string]: 1 }}>
        <h2 className="text-[15px] font-semibold text-ink">Goals</h2>
        <GoalChecklist className="mt-3" goals={report.goals.items} />
      </section>
      {report.next_steps.focus ? (
        <section className="reveal rounded-[18px] bg-accent-soft/70 p-5" style={{ ["--i" as string]: 2 }}>
          <p className="flex items-center gap-2 text-[13px] font-semibold text-accent-ink"><Icon name="target" size={16} /> Next time, focus on</p>
          <p className="mt-1.5 text-[16px] text-ink pretty">{report.next_steps.focus}</p>
        </section>
      ) : null}
      {report.native_language_turns > 0 ? (
        <p className="text-[13px] text-ink-3">You switched to your own language {plural(report.native_language_turns, "time")} — completely fine; next time try a simpler word in the target language first.</p>
      ) : null}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <p className="text-[13px] text-ink-2">{label}</p>
      <p className="mt-1 text-[26px] font-semibold leading-none text-ink">{value}</p>
      {hint ? <p className="mt-1.5 text-[12px] text-ink-3">{hint}</p> : null}
    </div>
  );
}

function Speaking({ report }: { report: Report }) {
  const sp = report.speaking;
  const cjk = report.language === "ko" || report.language === "ja";
  if (sp.estimated_from_text) {
    return <EmptyState icon="keyboard" title="This was a typed session" body="Speaking metrics come from your voice — pace, pauses and fillers. Try the next one out loud." />;
  }
  const fillers = Object.entries(sp.filler_counts);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3">
        <Stat label={cjk ? "Characters per minute" : "Words per minute"} value={String(Math.round(cjk ? sp.chars_per_minute : sp.words_per_minute))} hint={`${sp.rate_label} pace`} />
        <Stat label="Average reply delay" value={seconds(sp.avg_response_delay_ms)} hint="from their line ending to you speaking" />
        <Stat label="Longest pause" value={`${sp.longest_pause_s.toFixed(1)} s`} hint={sp.long_pauses[0] ? `after “${sp.long_pauses[0].after_word}”` : "none over 1.5 s"} />
        <Stat label="Fillers" value={String(sp.filler_total)} hint={fillers.length ? fillers.slice(0, 2).map(([f, n]) => `${f} ×${n}`).join(" · ") : "none — nice"} />
      </div>
      <section className="card p-5">
        <h2 className="text-[15px] font-semibold text-ink">Turn length</h2>
        <p className="mt-1 text-[14px] text-ink-2">
          {sp.turn_length_trend === "growing"
            ? "Your answers got longer as you warmed up — a great sign."
            : sp.turn_length_trend === "shrinking"
              ? "Your answers got shorter towards the end. Try adding one detail per reply."
              : "Your answers stayed about the same length throughout."}
        </p>
        <div className="mt-4 flex h-16 items-end gap-1" role="img" aria-label={`Words per turn: ${sp.words_per_turn.join(", ")}`}>
          {sp.words_per_turn.map((n, i) => (
            <span key={i} className="flex-1 rounded-t-[4px] bg-accent" style={{ height: `${Math.max(8, (n / Math.max(...sp.words_per_turn, 1)) * 100)}%`, maxWidth: 24 }} />
          ))}
        </div>
      </section>
      <p className="text-[12px] text-ink-3">Measured from the timing of each word in your recordings — not estimated by a model.</p>
    </div>
  );
}

function Grammar({ report, lang }: { report: Report; lang: Lang }) {
  const save = useSaveWord();
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const { guest } = useSessionInfo();
  const corrections = report.grammar.corrections;
  const reg = report.register;
  return (
    <div className="space-y-4">
      {corrections.length ? (
        <>
          <h2 className="font-display text-[24px] text-ink">{plural(corrections.length, "thing")} to polish</h2>
          {corrections.map((c, i) => (
            <CorrectionCard
              key={i}
              index={i}
              correction={c}
              lang={lang}
              onHear={(text) => void speak(text, lang)}
              saved={saved.has(i)}
              onSave={
                guest
                  ? undefined
                  : () =>
                      save.mutate(
                        { language: lang, term: c.better, meaning: c.why || "Corrected phrase", example: c.better, source_session_id: report.session_id },
                        { onSuccess: () => setSaved(new Set(saved).add(i)) },
                      )
              }
            />
          ))}
        </>
      ) : (
        <EmptyState icon="check" title="Nothing major to correct" body={report.grammar.note ?? "Your sentences held together well for this level."} />
      )}
      {lang !== "en" ? (
        <section className={cx("rounded-[18px] p-5", reg.consistent ? "bg-great-soft" : "bg-improve-soft")}>
          <p className={cx("flex items-center gap-2 text-[13px] font-semibold", reg.consistent ? "text-great" : "text-improve")}>
            <Icon name={reg.consistent ? "check" : "info"} size={16} /> Politeness level
            {reg.confidence === "low" ? <span className="font-normal opacity-80">· not enough to judge</span> : null}
          </p>
          <p className="mt-1.5 text-[15px] text-ink pretty">{reg.notes}</p>
        </section>
      ) : null}
    </div>
  );
}

function Vocab({ report, lang }: { report: Report; lang: Lang }) {
  const v = report.vocabulary;
  const chips = (items: string[], tone: "great" | "neutral") =>
    items.length ? (
      <div className="mt-2 flex flex-wrap gap-1.5" lang={lang}>
        {items.map((w) => (
          <span key={w} className={cx("target rounded-full px-3 py-1 text-[15px]", tone === "great" ? "bg-great-soft text-great" : "bg-paper-2 text-ink")}>{w}</span>
        ))}
      </div>
    ) : (
      <p className="mt-2 text-[14px] text-ink-3">None this time.</p>
    );
  return (
    <div className="space-y-5">
      {v.target_hit_rate.rate != null ? (
        <section className="card p-5">
          <h2 className="text-[15px] font-semibold text-ink">Target words</h2>
          <p className="mt-1 text-[13px] text-ink-3">The scene’s key vocabulary — {Math.round((v.target_hit_rate.rate ?? 0) * 100)}% used.</p>
          <p className="mt-3 text-[12px] font-medium text-ink-2">Used</p>
          {chips(v.target_hit_rate.used, "great")}
          <p className="mt-3 text-[12px] font-medium text-ink-2">Not yet</p>
          {chips(v.target_hit_rate.missed, "neutral")}
        </section>
      ) : null}
      <section className="card p-5">
        <h2 className="text-[15px] font-semibold text-ink">Used well</h2>
        {chips(v.used_well, "great")}
        <h2 className="mt-5 text-[15px] font-semibold text-ink">New words you heard</h2>
        {chips(v.new, "neutral")}
      </section>
      {v.requires_account ? (
        <div className="rounded-[18px] bg-accent-soft/70 p-5 text-[14px] text-ink">
          <Link href="/settings#account" className="font-semibold text-accent-ink underline-offset-4 hover:underline">Create an account</Link> and suggested words become flashcards automatically.
        </div>
      ) : v.flashcards_created.length ? (
        <p className="text-[14px] text-ink-2">
          <Icon name="cards" size={16} className="mr-1 inline" /> {plural(v.flashcards_created.length, "flashcard")} added: {v.flashcards_created.map((f) => f.term).join(", ")}. <Link className="font-medium text-accent-ink" href="/vocab">Review →</Link>
        </p>
      ) : null}
    </div>
  );
}

function Pronunciation({ report, lang }: { report: Report; lang: Lang }) {
  const p = report.pronunciation;
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-2 rounded-2xl bg-paper-2 p-4 text-[13.5px] text-ink-2">
        <Icon name="info" size={16} className="mt-0.5 shrink-0" />
        <p className="pretty">{p.disclaimer}</p>
      </div>
      {p.unclear_words.length ? (
        <section className="card p-5">
          <h2 className="text-[15px] font-semibold text-ink">Words that may have been unclear</h2>
          <ul className="mt-3 space-y-2">
            {p.unclear_words.map((u, i) => (
              <li key={i} className="flex items-center gap-3">
                <span lang={lang} className="target min-w-[4rem] text-[18px] font-medium text-ink">{u.word}</span>
                <span className="text-[12px] text-ink-3">turn {u.turn_idx}</span>
                <button onClick={() => void speak(u.word, lang, 0.85)} className="tap ml-auto inline-flex items-center gap-1 rounded-full px-3 text-[13px] font-medium text-accent-ink hover:bg-accent-soft">
                  <Icon name="speaker" size={15} /> Hear it
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <EmptyState icon="check" title={p.basis === "unavailable" ? "No audio to check" : "Nothing flagged"} body={p.basis === "unavailable" ? "Speak the next session out loud to get pronunciation hints." : "Speech recognition understood every word clearly."} />
      )}
      {p.focus_areas ? (
        <section className="rounded-[18px] bg-accent-soft/60 p-5">
          <p className="text-[13px] font-semibold text-accent-ink">Common focus areas in {LANGS[lang].name}</p>
          <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-2 pretty">{p.focus_areas}</p>
        </section>
      ) : null}
      {p.drills.length ? (
        <LinkButton href={`/session/${report.session_id}/drills`} icon="mic" className="w-full">
          Practise with scored drills ({p.drills.length})
        </LinkButton>
      ) : null}
    </div>
  );
}

function Transcript({ report, lang }: { report: Report; lang: Lang }) {
  const corrected = new Set(report.grammar.corrections.map((c) => c.turn).filter((t): t is number => t != null));
  const unclear = new Set(report.pronunciation.unclear_words.map((u) => u.turn_idx));
  return (
    <ol className="space-y-3">
      {report.transcript.map((line) => (
        <li key={line.idx} className={cx("flex gap-3", line.role === "user" && "flex-row-reverse text-right")}>
          <span className="mt-1 w-6 shrink-0 text-center text-[11px] text-ink-3 tabular">{line.idx}</span>
          <div className={cx("max-w-[85%] rounded-2xl px-4 py-2.5", line.role === "user" ? "bg-ink text-paper" : "bg-card hairline")}>
            <button onClick={() => void speak(line.text, lang)} className="text-left">
              <span lang={lang} className="target text-[16px]">{line.text}</span>
            </button>
            {line.role === "ai" && line.translation_en ? <p className="mt-1 text-[13px] text-ink-3">{line.translation_en}</p> : null}
            {(corrected.has(line.idx) || unclear.has(line.idx)) && line.role === "user" ? (
              <div className="mt-1.5 flex flex-wrap justify-end gap-1">
                {corrected.has(line.idx) ? <span className="rounded-full bg-improve-soft px-2 py-0.5 text-[11px] font-semibold text-improve">correction</span> : null}
                {unclear.has(line.idx) ? <span className="rounded-full bg-paper/20 px-2 py-0.5 text-[11px] font-semibold">unclear word (est.)</span> : null}
              </div>
            ) : null}
          </div>
        </li>
      ))}
      <li className="pt-3 text-center text-[12px] text-ink-3">
        <LevelBadge level={report.level} /> Tap any line to hear it.
      </li>
    </ol>
  );
}
