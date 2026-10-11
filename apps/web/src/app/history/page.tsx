"use client";

import type { SessionSummary } from "@talkscene/sdk";
import Link from "next/link";
import { useMemo } from "react";

import { Page } from "@/components/AppShell";
import { BandBadge, EmptyState, ErrorBanner, LevelBadge } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Display, Skeleton } from "@/components/ui";
import { problemMessage, useSessionInfo, useSessions } from "@/lib/api";
import { useHydrated } from "@/lib/client-state";
import { relativeDay } from "@/lib/format";

export default function History() {
  const { data, isPending, error, refetch } = useSessions();
  const hydrated = useHydrated();
  const { signedIn } = useSessionInfo();
  const isLoading = !hydrated || (signedIn && isPending);

  const groups = useMemo(() => {
    const out = new Map<string, SessionSummary[]>();
    for (const s of data?.items ?? []) {
      const day = relativeDay(s.started_at);
      out.set(day, [...(out.get(day) ?? []), s]);
    }
    return [...out.entries()];
  }, [data]);

  return (
    <Page>
      <Display className="reveal text-[38px]">Past conversations</Display>
      {error ? <ErrorBanner className="mt-6" message={problemMessage(error)} onRetry={() => void refetch()} /> : null}
      {isLoading ? (
        <div className="mt-8 space-y-3">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : groups.length === 0 ? (
        <div className="mt-8">
          <EmptyState icon="clock" title="Nothing here yet" body="Your conversations and their reports will collect here." action={{ label: "Start a conversation", href: "/scenarios" }} />
        </div>
      ) : (
        groups.map(([day, sessions], g) => (
          <section key={day} className="mt-8" aria-labelledby={`day-${g}`}>
            <h2 id={`day-${g}`} className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-3">{day}</h2>
            <ul className="mt-3 space-y-2">
              {sessions.map((s, i) => {
                const done = s.status === "completed" || s.status === "analyzing";
                const href = done ? `/session/${s.session_id}/report` : s.status === "active" ? `/session/${s.session_id}` : `/scenarios/${s.scenario_id}`;
                return (
                  <li key={s.session_id} className="reveal" style={{ ["--i" as string]: i }}>
                    <Link href={href} data-lang={s.language} className="card flex items-center gap-4 p-4 transition hover:-translate-y-0.5">
                      <span className="emoji grid size-11 shrink-0 place-items-center rounded-2xl bg-accent-soft text-xl" aria-hidden>{s.icon ?? "💬"}</span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[15px] font-semibold text-ink">{s.scenario_title}</p>
                        <p className="mt-0.5 flex items-center gap-2 text-[12.5px] text-ink-3">
                          <LangMark lang={s.language} size="xs" />
                          <LevelBadge level={s.level} />
                          <span>{s.turns_used}/{s.target_turns} turns · {s.goals_done}/{s.goals_total} goals</span>
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        {s.overall != null ? (
                          <>
                            <span className="text-[22px] font-semibold leading-none text-ink">{s.overall}</span>
                            <BandBadge score={s.overall} />
                          </>
                        ) : s.status === "active" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-[12px] font-semibold text-accent-ink"><Icon name="play" size={12} /> Resume</span>
                        ) : (
                          <span className="text-[12px] capitalize text-ink-3">{s.status}</span>
                        )}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </Page>
  );
}
