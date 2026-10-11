"use client";

import type { Lang, Level } from "@talkscene/sdk";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { Page } from "@/components/AppShell";
import { ScenarioCard } from "@/components/catalog";
import { EmptyState, ErrorBanner } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Chip, Display, Skeleton } from "@/components/ui";
import { problemMessage, useScenarios } from "@/lib/api";
import { cx } from "@/lib/format";
import { CATEGORIES, LANG_ORDER, LANGS, LEVELS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

export default function Scenarios() {
  const prefs = usePrefs();
  const [lang, setLang] = useState<Lang | undefined>(prefs.lang ?? undefined);
  const [level, setLevel] = useState<Level | undefined>();
  const [category, setCategory] = useState<string | undefined>();
  const [sort, setSort] = useState<"recommended" | "newest" | "shortest">("recommended");
  const [query, setQuery] = useState("");
  const q = useDeferredValue(query.trim());

  const { data, isLoading, isFetching, error, refetch } = useScenarios({ lang, level, category, q: q || undefined, sort });

  return (
    <Page wide>
      <Display className="reveal text-[38px]">Scenes</Display>
      <p className="reveal mt-1 text-ink-2" style={{ ["--i" as string]: 1 }}>
        Real situations, written per language — not translations of each other.
      </p>

      {/* One filter row above everything it scopes. */}
      <div className="reveal sticky top-0 z-10 -mx-5 mt-6 space-y-3 bg-paper/90 px-5 py-3 backdrop-blur-xl md:top-[57px]" style={{ ["--i" as string]: 2 }}>
        <label className="relative block">
          <span className="sr-only">Search scenes</span>
          <Icon name="search" size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Hotel, pharmacy, interview…"
            className="h-12 w-full rounded-full bg-card pl-11 pr-4 text-[15px] text-ink outline-none hairline placeholder:text-ink-3 focus-visible:shadow-[inset_0_0_0_2px_var(--accent)]"
          />
        </label>
        <div className="-mx-5 flex gap-2 overflow-x-auto px-5 scrollbar-none">
          <Chip selected={!lang} onClick={() => setLang(undefined)}>
            All languages
          </Chip>
          {LANG_ORDER.map((code) => (
            <Chip key={code} selected={lang === code} onClick={() => setLang(code)}>
              <LangMark lang={code} size="xs" /> {LANGS[code].name}
            </Chip>
          ))}
          <span className="mx-1 w-px shrink-0 self-stretch bg-line" aria-hidden />
          {LEVELS.map((l) => (
            <Chip key={l.level} selected={level === l.level} onClick={() => setLevel(level === l.level ? undefined : l.level)}>
              {l.level}
            </Chip>
          ))}
        </div>
        <div className="-mx-5 flex items-center gap-1 overflow-x-auto px-5 scrollbar-none" role="tablist" aria-label="Category">
          {[{ id: undefined, label: "Everything", icon: "✦" }, ...CATEGORIES].map((c) => (
            <button
              key={c.label}
              role="tab"
              aria-selected={category === c.id}
              onClick={() => setCategory(c.id)}
              className={cx(
                "tap relative inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 text-[14px] font-medium transition",
                "after:absolute after:inset-x-3 after:bottom-1 after:h-0.5 after:rounded-full after:transition",
                category === c.id ? "text-ink after:bg-accent" : "text-ink-3 after:bg-transparent hover:text-ink-2",
              )}
            >
              <span aria-hidden className="emoji">{c.icon}</span>
              {c.label}
            </button>
          ))}
          <label className="ml-auto flex shrink-0 items-center gap-1.5 pl-3 text-[13px] text-ink-3">
            Sort
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as typeof sort)}
              className="tap rounded-full bg-card px-3 text-[13px] font-medium text-ink outline-none hairline"
            >
              <option value="recommended">Recommended</option>
              <option value="newest">Newest</option>
              <option value="shortest">Shortest</option>
            </select>
          </label>
        </div>
      </div>

      {error ? <ErrorBanner className="mt-6" message={problemMessage(error)} onRetry={() => void refetch()} /> : null}

      {/* Refetch keeps the frame: dim the previous results instead of flashing skeletons. */}
      <div className={cx("mt-6 grid gap-3 transition-opacity sm:grid-cols-2 lg:grid-cols-3", isFetching && !isLoading && "opacity-60")}>
        {isLoading
          ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-44" />)
          : data?.items.map((s, i) => <ScenarioCard key={s.id} scenario={s} index={i % 9} />)}
        {!isLoading ? (
          <Link
            href="/create"
            className="reveal flex min-h-[11rem] flex-col items-center justify-center rounded-[18px] border-2 border-dashed border-line-strong p-5 text-center text-ink-2 transition hover:border-accent hover:text-accent-ink"
          >
            <Icon name="wand" size={26} />
            <span className="mt-2 text-[15px] font-semibold">Create your own</span>
            <span className="mt-1 text-[13px]">Describe any situation in a sentence.</span>
          </Link>
        ) : null}
      </div>

      {!isLoading && data && data.items.length === 0 ? (
        <div className="mt-6">
          <EmptyState icon="search" title="No scenes match" body="Try another level or category — or describe the scene you want and we will build it." action={{ label: "Create a scene", href: "/create" }} />
        </div>
      ) : null}
    </Page>
  );
}
