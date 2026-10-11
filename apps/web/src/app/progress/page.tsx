"use client";

import Link from "next/link";
import { useMemo } from "react";

import { Page } from "@/components/AppShell";
import { MinutesChart, PracticeCalendar, ScoreSparkline, SkillBars } from "@/components/charts";
import { EmptyState, ErrorBanner } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Display, Skeleton } from "@/components/ui";
import { problemMessage, useProgress, useSessionInfo } from "@/lib/api";
import { useHydrated } from "@/lib/client-state";
import { LANGS } from "@/lib/lang";

export default function ProgressPage() {
  const { data, isPending, error, refetch } = useProgress();
  const hydrated = useHydrated();
  const { signedIn } = useSessionInfo();

  const last7 = useMemo(() => {
    const byDate = new Map((data?.activity ?? []).map((a) => [a.date, a]));
    const out: { date: string; minutes: number; sessions: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const a = byDate.get(key);
      out.push({ date: key, minutes: a?.minutes ?? 0, sessions: a?.sessions ?? 0 });
    }
    return out;
  }, [data]);

  // `isPending` (not `isLoading`) also covers a query that has not been enabled
  // yet, so the prerender, the first client render and the fetch all agree.
  if (!hydrated || (signedIn && isPending)) return <Page><Skeleton className="h-10 w-1/2" /><Skeleton className="mt-6 h-48" /><Skeleton className="mt-4 h-64" /></Page>;
  if (error) return <Page><ErrorBanner message={problemMessage(error)} onRetry={() => void refetch()} /></Page>;
  if (!data || data.sessions_total === 0) {
    return (
      <Page>
        <Display className="reveal text-[38px]">Progress</Display>
        <div className="mt-8"><EmptyState icon="chart" title="Your progress starts with one conversation" body="Finish a scene and this page fills with your minutes, streak, and how each skill is moving." action={{ label: "Pick a scene", href: "/scenarios" }} /></div>
      </Page>
    );
  }

  const radar = data.skill_radar;
  return (
    <Page wide>
      <div className="flex items-end justify-between">
        <Display className="reveal text-[38px]">Progress</Display>
        <Link href="/history" className="tap inline-flex items-center gap-1 rounded-full px-3 text-[14px] font-medium text-accent-ink">History <Icon name="forward" size={16} /></Link>
      </div>

      {/* KPI row: headline numbers are stat tiles, not charts. */}
      <div className="reveal mt-6 grid grid-cols-2 gap-3 md:grid-cols-4" style={{ ["--i" as string]: 1 }}>
        {[
          ["Day streak", String(data.streak_days), "flame"],
          ["Minutes practised", String(Math.round(data.minutes_total)), "clock"],
          ["Conversations", String(data.sessions_total), "sparkle"],
          ["Words saved", String(data.words_learned), "cards"],
        ].map(([label, value, icon]) => (
          <div key={label} className="card p-4">
            <p className="flex items-center gap-1.5 text-[13px] text-ink-2"><Icon name={icon as "flame"} size={15} /> {label}</p>
            <p className="mt-1.5 text-[30px] font-semibold leading-none text-ink">{value}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section className="card reveal p-5" style={{ ["--i" as string]: 2 }} aria-labelledby="week">
          <h2 id="week" className="text-[15px] font-semibold text-ink">Minutes this week</h2>
          <p className="text-[13px] text-ink-3">Daily goal {data.daily_goal_minutes} minutes</p>
          <div className="mt-4"><MinutesChart days={last7} goal={data.daily_goal_minutes} /></div>
        </section>
        <section className="card reveal p-5" style={{ ["--i" as string]: 3 }} aria-labelledby="cal">
          <h2 id="cal" className="text-[15px] font-semibold text-ink">Last five weeks</h2>
          <p className="text-[13px] text-ink-3">Shaded by how close each day came to your goal</p>
          <div className="mt-4"><PracticeCalendar activity={data.activity} goal={data.daily_goal_minutes} /></div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-[1fr_1.4fr]">
        {data.score_trend.length >= 2 ? (
          <section className="card reveal p-5" style={{ ["--i" as string]: 4 }} aria-labelledby="trend">
            <h2 id="trend" className="text-[15px] font-semibold text-ink">Overall score</h2>
            <p className="mt-1.5 text-[34px] font-semibold leading-none text-ink">{data.score_trend[data.score_trend.length - 1]}</p>
            <p className="text-[13px] text-ink-3">
              {(() => {
                const t = data.score_trend;
                const delta = t[t.length - 1]! - t[0]!;
                return `${delta >= 0 ? "+" : "−"}${Math.abs(delta)} since your first of these ${t.length} sessions`;
              })()}
            </p>
            <div className="mt-4"><ScoreSparkline scores={data.score_trend} /></div>
          </section>
        ) : null}
        {radar ? (
          <section className="card reveal p-5" style={{ ["--i" as string]: 5 }} aria-labelledby="skills">
            <h2 id="skills" className="text-[15px] font-semibold text-ink">Skills, last five sessions</h2>
            <div className="mt-4">
              <SkillBars
                overall={Math.round(data.score_trend[data.score_trend.length - 1] ?? 0)}
                rows={[
                  { key: "task", label: "Task completion", value: radar.task_completion, weight: 0.3, explanation: "How often you reach the scene’s goals." },
                  { key: "grammar", label: "Grammar & accuracy", value: radar.grammar, weight: 0.25, explanation: "Fewer, smaller corrections over time." },
                  { key: "fluency", label: "Fluency", value: radar.fluency, weight: 0.2, explanation: "Pace, pauses and fillers in spoken sessions." },
                  { key: "pron", label: "Pronunciation (estimated)", value: radar.pronunciation || null, weight: 0.15, excluded: !radar.pronunciation, explanation: radar.pronunciation ? "Estimated from speech recognition — drills give real scores." : "Not measured yet — speak a session out loud." },
                  { key: "vocab", label: "Vocabulary range", value: radar.vocabulary, weight: 0.1, explanation: "How many of each scene’s key words you use." },
                ]}
              />
            </div>
          </section>
        ) : null}
      </div>

      {data.by_language.length ? (
        <section className="card reveal mt-4 overflow-hidden" style={{ ["--i" as string]: 6 }} aria-labelledby="langs">
          <h2 id="langs" className="px-5 pt-5 text-[15px] font-semibold text-ink">By language</h2>
          <table className="mt-3 w-full text-left text-[14px]">
            <thead className="text-[12px] text-ink-3">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2 font-medium">Language</th>
                <th scope="col" className="py-2 pr-4 font-medium">Sessions</th>
                <th scope="col" className="py-2 pr-4 font-medium">Minutes</th>
                <th scope="col" className="py-2 pr-4 font-medium">Avg score</th>
                <th scope="col" className="py-2 pr-5 font-medium">Level</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {data.by_language.map((row) => (
                <tr key={row.language} className="border-b border-line/60 last:border-0">
                  <td className="px-5 py-3 text-ink"><span className="inline-flex items-center gap-2"><LangMark lang={row.language} size="xs" /> {LANGS[row.language].name}</span></td>
                  <td className="py-3 pr-4 text-ink-2">{row.sessions}</td>
                  <td className="py-3 pr-4 text-ink-2">{Math.round(row.minutes)}</td>
                  <td className="py-3 pr-4 text-ink-2">{row.avg_score ?? "—"}</td>
                  <td className="py-3 pr-5 text-ink-2">{row.latest_cefr ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </Page>
  );
}
