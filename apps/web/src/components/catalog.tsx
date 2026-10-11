"use client";

import type { Lang, ScenarioCard as Card } from "@talkscene/sdk";
import Link from "next/link";

import { cx } from "@/lib/format";
import { LANG_ORDER, LANGS } from "@/lib/lang";

import { LevelBadge } from "./feedback";
import { LangMark } from "./LangMark";
import { Icon } from "./Icon";

/** Library card (plan §11.3 C): icon, both titles, level, duration, completion. */
export function ScenarioCard({ scenario, index = 0, compact }: { scenario: Card; index?: number; compact?: boolean }) {
  const lang = scenario.language as Lang;
  const target = lang !== "en" ? scenario.title[lang] : undefined;
  return (
    <Link
      href={`/scenarios/${scenario.id}`}
      data-lang={lang}
      style={{ ["--i" as string]: index }}
      className={cx(
        "card reveal group relative flex flex-col overflow-hidden p-4 transition duration-300",
        "hover:-translate-y-0.5 hover:shadow-[inset_0_0_0_1px_var(--line-strong),0_18px_40px_-20px_rgb(27_24_20/0.3)]",
        compact ? "min-w-[13.5rem]" : "min-h-[11rem]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="emoji grid size-11 place-items-center rounded-2xl bg-paper-2 text-2xl" aria-hidden>
          {scenario.icon ?? "💬"}
        </span>
        <div className="flex items-center gap-1.5">
          {scenario.completed ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-great-soft px-2 py-0.5 text-[11px] font-semibold text-great">
              <Icon name="check" size={12} />
              {scenario.best_score != null ? scenario.best_score : "Done"}
            </span>
          ) : null}
          <LevelBadge level={scenario.level} />
        </div>
      </div>
      <div className="mt-4 flex-1">
        {target ? (
          <p lang={lang} className="target text-[13px] text-ink-3">
            {target}
          </p>
        ) : null}
        <h3 className="mt-0.5 text-[16px] font-semibold leading-snug text-ink">{scenario.title.en}</h3>
        {!compact ? <p className="mt-1.5 line-clamp-2 text-[13.5px] leading-snug text-ink-2">{scenario.summary}</p> : null}
      </div>
      <div className="mt-3 flex items-center gap-3 text-[12px] text-ink-3">
        <span className="inline-flex items-center gap-1">
          <Icon name="clock" size={14} /> ~{scenario.estimated_minutes} min
        </span>
        <span className="inline-flex items-center gap-1.5">
          <LangMark lang={lang} size="xs" /> {LANGS[lang].name}
        </span>
        <Icon name="arrow" size={16} className="ml-auto text-ink-3 transition group-hover:translate-x-0.5 group-hover:text-accent-ink" />
      </div>
    </Link>
  );
}

export function LanguagePicker({
  value,
  onChange,
  counts,
}: {
  value: Lang | null;
  onChange: (lang: Lang) => void;
  counts?: Partial<Record<Lang, number>>;
}) {
  return (
    <div role="radiogroup" aria-label="Language to learn" className="grid grid-cols-2 gap-3">
      {LANG_ORDER.map((code, i) => {
        const meta = LANGS[code];
        const selected = value === code;
        return (
          <button
            key={code}
            role="radio"
            aria-checked={selected}
            data-lang={code}
            onClick={() => onChange(code)}
            style={{ ["--i" as string]: i }}
            className={cx(
              "reveal relative flex flex-col items-start overflow-hidden rounded-[22px] p-4 text-left transition duration-300",
              selected
                ? "bg-accent text-on-accent shadow-[0_18px_40px_-18px_rgb(var(--glow)/0.9)]"
                : "bg-card text-ink hairline hover:-translate-y-0.5",
            )}
          >
            <LangMark lang={code} size="md" className={selected ? "bg-on-accent/20 text-on-accent" : ""} />
            <span lang={code} className={cx("target mt-6 text-[22px] font-medium leading-none", selected ? "" : "text-ink")}>
              {meta.hello}
            </span>
            <span className={cx("mt-2 text-[13px] font-medium", selected ? "opacity-90" : "text-ink-2")}>
              {meta.name}
              {counts?.[code] ? <span className="opacity-70"> · {counts[code]} scenes</span> : null}
            </span>
            {selected ? (
              <span className="absolute right-3 top-3 grid size-6 place-items-center rounded-full bg-on-accent/20">
                <Icon name="check" size={14} strokeWidth={2.5} />
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Quota meter (plan §11.3 J, §14.3). The fill carries severity — accent while
 * comfortable, warning from 70% used, critical from 90% — and the track is a
 * lighter step of the fill's own hue. Severity is also spelled out in words.
 */
export function QuotaMeter({
  label,
  used,
  limit,
  unit,
  resets,
}: {
  label: string;
  used: number;
  limit: number | null | undefined;
  unit: string;
  resets: string;
}) {
  if (limit == null || limit === 0) {
    return (
      <div className="flex items-center justify-between py-3">
        <span className="text-[14px] text-ink">{label}</span>
        <span className="text-[13px] text-ink-3">Unlimited</span>
      </div>
    );
  }
  const ratio = Math.min(1, used / limit);
  const leftPct = Math.max(0, Math.round((1 - ratio) * 100));
  const level = ratio >= 0.9 ? "critical" : ratio >= 0.7 ? "warning" : "ok";
  const fill = { ok: "var(--accent)", warning: "var(--improve)", critical: "var(--attention)" }[level];
  const track = { ok: "var(--accent-soft)", warning: "var(--improve-soft)", critical: "var(--attention-soft)" }[level];
  return (
    <div className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[14px] text-ink">{label}</span>
        <span className="text-[13px] text-ink-2">
          {level !== "ok" ? (
            <span className="mr-1.5 inline-flex items-center gap-1 font-medium">
              <Icon name="alert" size={13} /> {level === "critical" ? "Almost out" : "Running low"} ·
            </span>
          ) : null}
          {leftPct}% left
        </span>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full"
        style={{ background: track }}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={Math.round(used)}
        aria-valuetext={`${Math.round(used).toLocaleString()} of ${limit.toLocaleString()} ${unit} used, resets ${resets}`}
      >
        <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${ratio * 100}%`, background: fill }} />
      </div>
      <p className="mt-1 text-[12px] text-ink-3">
        {Math.round(used).toLocaleString()} / {limit.toLocaleString()} {unit} · resets {resets}
      </p>
    </div>
  );
}
