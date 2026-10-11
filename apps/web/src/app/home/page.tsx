"use client";

import Link from "next/link";
import { useHydrated, useSessionInfo } from "@/lib/client-state";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Page } from "@/components/AppShell";
import { ScenarioCard } from "@/components/catalog";
import { EmptyState } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Display, Eyebrow, LinkButton, Skeleton } from "@/components/ui";
import { useMe, useProgress, useScenarios, useSessions } from "@/lib/api";
import { greeting, plural } from "@/lib/format";
import { LANGS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

export default function Home() {
  const router = useRouter();
  const { lang, level, onboarded, hydrated, dailyGoal } = usePrefs();
  const mounted = useHydrated();
  const { guest } = useSessionInfo();
  const me = useMe();
  const sessions = useSessions();
  const progress = useProgress();
  const recommended = useScenarios({ lang: lang ?? undefined, level, limit: 8 });

  useEffect(() => {
    if (hydrated && !onboarded) router.replace("/onboarding");
  }, [hydrated, onboarded, router]);

  const active = sessions.data?.items.find((s) => s.status === "active");
  const goal = progress.data?.daily_goal_minutes ?? dailyGoal;
  const today = progress.data?.minutes_today ?? 0;
  const due = progress.data?.cards_due ?? 0;
  const name = me.data?.display_name;
  const streak = me.data?.streak_days ?? progress.data?.streak_days ?? 0;
  const unplayed = (recommended.data?.items ?? []).filter((s) => !s.completed);
  const picks = (unplayed.length >= 3 ? unplayed : recommended.data?.items ?? []).slice(0, 6);

  return (
    <Page>
      <header className="reveal flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            {lang ? <LangMark lang={lang} size="xs" /> : null}
            <Eyebrow>{lang ? `${LANGS[lang].name} · ${level}` : "Welcome"}</Eyebrow>
          </div>
          <Display className="mt-2 text-[36px] leading-[1.05]">
            {/* The page is prerendered; the local hour exists only in the browser. */}
            {mounted ? greeting() : "Welcome back"}
            {name ? `, ${name}` : ""}.
          </Display>
        </div>
        {streak > 0 ? (
          <div className="flex shrink-0 items-center gap-1.5 rounded-full bg-improve-soft px-3 py-1.5 text-improve" title={`${streak}-day streak`}>
            <Icon name="flame" size={18} />
            <span className="text-[15px] font-semibold">{streak}</span>
            <span className="sr-only">day streak</span>
          </div>
        ) : null}
      </header>

      {active ? (
        <Link
          href={`/session/${active.session_id}`}
          className="card reveal group mt-8 flex items-center gap-4 p-5"
          style={{ ["--i" as string]: 1 }}
          data-lang={active.language}
        >
          <span className="emoji grid size-12 place-items-center rounded-2xl bg-accent-soft text-2xl" aria-hidden>
            {active.icon ?? "💬"}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-accent-ink">Continue</p>
            <p className="truncate text-[16px] font-semibold text-ink">{active.scenario_title}</p>
            <p className="text-[13px] text-ink-2">
              Turn {active.turns_used} of {active.target_turns} · {active.goals_done}/{active.goals_total} goals
            </p>
          </div>
          <span className="tap grid place-items-center rounded-full bg-accent text-on-accent transition group-hover:scale-105">
            <Icon name="play" size={18} />
          </span>
        </Link>
      ) : null}

      <section className="reveal mt-8" style={{ ["--i" as string]: 2 }} aria-labelledby="today">
        <div className="grid grid-cols-2 gap-3">
          <div className="card p-4">
            <p id="today" className="text-[13px] text-ink-2">Today</p>
            <p className="mt-1 text-[30px] font-semibold leading-none text-ink">
              {Math.round(today)}
              <span className="ml-1 text-[15px] font-medium text-ink-3">/ {goal} min</span>
            </p>
            <div
              className="mt-3 h-2 rounded-full bg-accent-soft"
              role="meter"
              aria-label="Daily goal"
              aria-valuemin={0}
              aria-valuemax={goal}
              aria-valuenow={Math.min(goal, Math.round(today))}
            >
              <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${Math.min(100, (today / goal) * 100)}%` }} />
            </div>
            <p className="mt-2 text-[12px] text-ink-3">{today >= goal ? "Goal met — nice." : `${Math.max(0, Math.ceil(goal - today))} min to your goal`}</p>
          </div>
          <Link href="/vocab" className="card group flex flex-col p-4 transition hover:-translate-y-0.5">
            <p className="text-[13px] text-ink-2">Flashcards</p>
            <p className="mt-1 text-[30px] font-semibold leading-none text-ink">{guest ? "—" : due}</p>
            <p className="mt-auto pt-3 text-[12px] font-medium text-accent-ink">
              {guest ? "Sign up to save words" : due ? `Review ${plural(due, "card")} →` : "All caught up"}
            </p>
          </Link>
        </div>
      </section>

      <section className="mt-10" aria-labelledby="rec">
        <div className="flex items-end justify-between">
          <h2 id="rec" className="font-display text-[24px] text-ink">
            Recommended for you
          </h2>
          <Link href="/scenarios" className="tap inline-flex items-center rounded-full px-2 text-[14px] font-medium text-accent-ink">
            See all
          </Link>
        </div>
        <div className="-mx-5 mt-4 flex snap-x gap-3 overflow-x-auto px-5 pb-2 scrollbar-none md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0">
          {recommended.isLoading
            ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-44 min-w-[13.5rem] md:min-w-0" />)
            : picks.map((s, i) => (
                <div key={s.id} className="snap-start">
                  <ScenarioCard scenario={s} index={i} compact />
                </div>
              ))}
        </div>
        {!recommended.isLoading && picks.length === 0 ? (
          <EmptyState
            title="Pick a language to begin"
            body="Choose what you want to speak and we will line up scenes at your level."
            action={{ label: "Choose a language", href: "/onboarding" }}
          />
        ) : null}
      </section>

      <section className="reveal mt-10 grid gap-3 md:grid-cols-2" style={{ ["--i" as string]: 3 }}>
        <Link href="/create" className="card group flex items-center gap-4 p-5 transition hover:-translate-y-0.5">
          <span className="grid size-11 place-items-center rounded-2xl bg-accent-soft text-accent-ink">
            <Icon name="wand" size={22} />
          </span>
          <span className="flex-1">
            <span className="block text-[15px] font-semibold text-ink">Create your own scene</span>
            <span className="block text-[13px] text-ink-2">“Complaining about a noisy neighbour…”</span>
          </span>
          <Icon name="forward" size={18} className="text-ink-3" />
        </Link>
        <Link href="/history" className="card group flex items-center gap-4 p-5 transition hover:-translate-y-0.5">
          <span className="grid size-11 place-items-center rounded-2xl bg-paper-2 text-ink-2">
            <Icon name="clock" size={22} />
          </span>
          <span className="flex-1">
            <span className="block text-[15px] font-semibold text-ink">Past conversations</span>
            <span className="block text-[13px] text-ink-2">{sessions.data ? plural(sessions.data.total ?? 0, "session") : "Your history"}</span>
          </span>
          <Icon name="forward" size={18} className="text-ink-3" />
        </Link>
      </section>

      <div className="mt-10 flex justify-center">
        <LinkButton href="/scenarios" variant="secondary" icon="grid">
          Browse all scenes
        </LinkButton>
      </div>
    </Page>
  );
}
