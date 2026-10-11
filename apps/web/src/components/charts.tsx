"use client";

/**
 * Charts, drawn as inline SVG against the design tokens.
 *
 * Built to the dataviz method: the form follows the data's job (a meter for a
 * single 0-100 score, bars for comparing sub-scores, columns for minutes over
 * time, a one-hue heat grid for the calendar, a sparkline inside a stat tile);
 * thin marks with 4px data-ends square at the baseline; solid hairline grids;
 * text always in ink tokens, never in the series colour; every value reachable
 * without hover via a table view; keyboard focus shows what hover shows.
 *
 * The calendar's three heat steps are validated per accent and per mode (see
 * `--heat-*` in globals.css). Do not add a fourth by eye.
 */

import { useId, useMemo, useState, type ReactNode } from "react";

import { cx } from "@/lib/format";

// ── shared pieces ───────────────────────────────────────────────────────────
type Tip = { x: number; y: number; title: string; value: string; detail?: string } | null;

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-xl bg-ink px-3 py-2 text-paper shadow-lg"
      style={{ left: tip.x, top: tip.y - 10 }}
    >
      {/* Value leads, label follows: the reader already knows what they hovered. */}
      <p className="text-[15px] font-semibold leading-tight">{tip.value}</p>
      <p className="text-[12px] leading-tight text-paper/70">{tip.title}</p>
      {tip.detail ? <p className="mt-0.5 text-[11px] leading-tight text-paper/60">{tip.detail}</p> : null}
    </div>
  );
}

/** Every chart has a table twin: the WCAG-clean way to read the same numbers. */
function DataTable({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="group mt-3">
      <summary className="tap inline-flex cursor-pointer list-none items-center gap-1 rounded-full px-2 text-[12px] font-medium text-ink-3 hover:text-ink-2">
        <span className="group-open:hidden">Show as table</span>
        <span className="hidden group-open:inline">Hide table</span>
      </summary>
      <table className="mt-2 w-full text-left text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line text-ink-3">
            {head.map((h) => (
              <th key={h} scope="col" className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular text-ink-2">
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line/60">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** SVG path for a bar with a 4px rounded data-end and a square baseline. */
function barPath(x: number, y: number, w: number, h: number, horizontal = false): string {
  if (h <= 0 || w <= 0) return "";
  if (horizontal) {
    const r = Math.min(4, w / 2, h / 2);
    return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`;
  }
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

// ── score meter ─────────────────────────────────────────────────────────────
/**
 * A single score against its 0-100 limit is a meter, not a chart. The track is
 * a lighter step of the fill's own hue; the number is the hero figure, in the
 * same sans as the UI with proportional digits.
 */
export function ScoreMeter({ value, size = 168, label = "Overall score" }: { value: number; size?: number; label?: string }) {
  const stroke = 10;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, value));
  const offset = circumference * (1 - clamped / 100);
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${clamped} out of 100`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--accent-soft)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ ["--dash" as string]: circumference, ["--to" as string]: offset, animation: "draw 1.1s var(--ease-out-soft) both" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-content-center text-center" aria-hidden>
        <span className="text-[52px] font-semibold leading-none tracking-[-0.03em] text-ink">{clamped}</span>
        <span className="mt-1 text-[12px] font-medium text-ink-3">of 100</span>
      </div>
    </div>
  );
}

// ── skill bars ──────────────────────────────────────────────────────────────
export type SkillRow = {
  key: string;
  label: string;
  value: number | null;
  weight: number;
  explanation: string;
  excluded?: boolean;
};

/**
 * Sub-scores as thin horizontal bars, each with its weight and a plain-English
 * reason (plan §8.3: "never opaque numbers alone"). Bars rather than a radar:
 * comparing five magnitudes is a bar's job, and a radar has nowhere to put the
 * explanations the plan requires.
 */
export function SkillBars({ rows, overall }: { rows: SkillRow[]; overall: number }) {
  const [tip, setTip] = useState<Tip>(null);
  const width = 100; // percentage space
  return (
    <div className="relative" onPointerLeave={() => setTip(null)}>
      <ul className="space-y-5">
        {rows.map((row) => {
          const v = row.value;
          const contribution = v == null || row.excluded ? null : (v * row.weight).toFixed(1);
          const readout =
            v == null || row.excluded
              ? `${row.label}: not measured this session`
              : `${row.label}: ${Math.round(v)} out of 100, weighted ${Math.round(row.weight * 100)}%`;
          return (
            <li key={row.key}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[14px] font-medium text-ink">{row.label}</span>
                <span className="text-[12px] text-ink-3">
                  {Math.round(row.weight * 100)}% of overall
                </span>
              </div>
              <div
                tabIndex={0}
                aria-label={readout}
                className="group relative mt-1.5 flex h-6 items-center gap-2 rounded-md outline-none"
                onPointerMove={(e) => {
                  const box = (e.currentTarget.parentElement?.parentElement as HTMLElement).getBoundingClientRect();
                  setTip({
                    x: e.clientX - box.left,
                    y: e.clientY - box.top,
                    title: row.label,
                    value: v == null || row.excluded ? "Not measured" : `${Math.round(v)} / 100`,
                    detail: contribution ? `Adds ${contribution} of the ${overall} overall points` : "Excluded from the overall score",
                  });
                }}
                onFocus={(e) => {
                  const box = (e.currentTarget.parentElement?.parentElement as HTMLElement).getBoundingClientRect();
                  const own = e.currentTarget.getBoundingClientRect();
                  setTip({
                    x: own.left - box.left + own.width / 2,
                    y: own.top - box.top,
                    title: row.label,
                    value: v == null || row.excluded ? "Not measured" : `${Math.round(v)} / 100`,
                    detail: contribution ? `Adds ${contribution} of the ${overall} overall points` : "Excluded from the overall score",
                  });
                }}
                onBlur={() => setTip(null)}
              >
                {v == null || row.excluded ? (
                  <>
                    {/* An empty track keeps the rows aligned; the reason is in the line below. */}
                    <svg viewBox={`0 0 ${width} 8`} preserveAspectRatio="none" className="h-2 flex-1" aria-hidden>
                      <rect x="0" y="0" width={width} height="8" rx="4" fill="var(--paper-2)" />
                    </svg>
                    <span className="w-8 text-right text-[14px] font-semibold text-ink-3">—</span>
                  </>
                ) : (
                  <>
                    <svg viewBox={`0 0 ${width} 8`} preserveAspectRatio="none" className="h-2 flex-1 overflow-visible" aria-hidden>
                      <rect x="0" y="0" width={width} height="8" rx="4" fill="var(--accent-soft)" />
                      <path d={barPath(0, 0, (Math.max(0, Math.min(100, v)) / 100) * width, 8, true)} fill="var(--accent)" />
                    </svg>
                    <span className="w-8 text-right text-[14px] font-semibold text-ink">{Math.round(v)}</span>
                  </>
                )}
              </div>
              <p className="mt-1 text-[13px] leading-snug text-ink-2 pretty">{row.explanation}</p>
            </li>
          );
        })}
      </ul>
      <Tooltip tip={tip} />
      <DataTable
        caption="Sub-scores"
        head={["Skill", "Score", "Weight"]}
        rows={rows.map((r) => [r.label, r.value == null || r.excluded ? "not measured" : Math.round(r.value), `${Math.round(r.weight * 100)}%`])}
      />
    </div>
  );
}

// ── minutes per day ─────────────────────────────────────────────────────────
export function MinutesChart({
  days,
  goal,
}: {
  days: { date: string; minutes: number; sessions: number }[];
  goal: number;
}) {
  const [tip, setTip] = useState<Tip>(null);
  const id = useId();
  const W = 320;
  const H = 150;
  const pad = { top: 18, right: 8, bottom: 24, left: 26 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const max = Math.max(goal * 1.25, ...days.map((d) => d.minutes), 5);
  const niceMax = Math.ceil(max / 5) * 5;
  // Two ticks: the goal line is labelled itself, and a mid tick like "8" reads as noise.
  const ticks = [0, niceMax];
  const slot = plotW / Math.max(days.length, 1);
  const barW = Math.min(24, slot - 2); // 2px surface gap between neighbours
  const y = (v: number) => pad.top + plotH - (v / niceMax) * plotH;
  const peak = days.reduce((best, d, i) => (d.minutes > (days[best]?.minutes ?? -1) ? i : best), 0);
  const todayIdx = days.length - 1;

  return (
    <div className="relative" onPointerLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-labelledby={`${id}-t`}>
        <title id={`${id}-t`}>Minutes practised per day, last {days.length} days, with a {goal}-minute daily goal</title>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={W - pad.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" />
            <text x={pad.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-ink-3 tabular text-[9px]">
              {t}
            </text>
          </g>
        ))}
        {/* The goal is a threshold, which is exactly what a dash means. */}
        <line x1={pad.left} x2={W - pad.right} y1={y(goal)} y2={y(goal)} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" />
        <text x={W - pad.right} y={y(goal) - 4} textAnchor="end" className="fill-ink-3 text-[9px] font-medium">
          goal {goal}m
        </text>

        {days.map((d, i) => {
          const x = pad.left + i * slot + (slot - barW) / 2;
          const h = (d.minutes / niceMax) * plotH;
          const label = new Date(d.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
          const showValue = (i === todayIdx || i === peak) && d.minutes > 0;
          const show = (cx: number, cy: number) =>
            setTip({
              x: cx,
              y: cy,
              title: new Date(d.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }),
              value: `${Math.round(d.minutes)} min`,
              detail: `${d.sessions} session${d.sessions === 1 ? "" : "s"}${d.minutes >= goal ? " · goal met" : ""}`,
            });
          return (
            <g key={d.date}>
              <path d={barPath(x, y(d.minutes), barW, h)} fill="var(--accent)" opacity={i === todayIdx ? 1 : 0.82} />
              {showValue ? (
                <text x={x + barW / 2} y={y(d.minutes) - 4} textAnchor="middle" className="fill-ink-2 text-[9px] font-semibold">
                  {Math.round(d.minutes)}
                </text>
              ) : null}
              <text x={x + barW / 2} y={H - 8} textAnchor="middle" className={cx("text-[9px]", i === todayIdx ? "fill-ink font-semibold" : "fill-ink-3")}>
                {i === todayIdx ? "Today" : label}
              </text>
              {/* Hit target: the whole column slot, never just the painted bar. */}
              <rect
                x={pad.left + i * slot}
                y={pad.top}
                width={slot}
                height={plotH}
                fill="transparent"
                tabIndex={0}
                aria-label={`${label}: ${Math.round(d.minutes)} minutes`}
                className="cursor-pointer outline-none focus-visible:fill-[var(--accent-soft)]"
                onPointerMove={(e) => {
                  const box = (e.currentTarget.ownerSVGElement?.parentElement as HTMLElement).getBoundingClientRect();
                  show(e.clientX - box.left, e.clientY - box.top);
                }}
                onFocus={(e) => {
                  const svg = e.currentTarget.ownerSVGElement!;
                  const scale = svg.getBoundingClientRect().width / W;
                  show((x + barW / 2) * scale, y(d.minutes) * scale);
                }}
                onBlur={() => setTip(null)}
              />
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
      <DataTable
        caption="Minutes practised per day"
        head={["Day", "Minutes", "Sessions"]}
        rows={days.map((d) => [d.date, Math.round(d.minutes), d.sessions])}
      />
    </div>
  );
}

// ── practice calendar ───────────────────────────────────────────────────────
/**
 * Five weeks of practice as a one-hue heat grid: three validated steps plus
 * "no practice", binned against the learner's own daily goal so the colour
 * means "how close to my goal" rather than an arbitrary minute count.
 */
export function PracticeCalendar({
  activity,
  goal,
  weeks = 5,
}: {
  activity: { date: string; minutes: number; sessions: number }[];
  goal: number;
  weeks?: number;
}) {
  const [tip, setTip] = useState<Tip>(null);
  const byDate = useMemo(() => new Map(activity.map((a) => [a.date, a])), [activity]);

  const cells = useMemo(() => {
    const today = new Date();
    const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    // Align to the end of the current week (Sunday) so columns are whole weeks.
    const daysToSunday = (7 - end.getDay()) % 7;
    const last = new Date(end);
    last.setDate(end.getDate() + daysToSunday);
    const out: { date: string; day: number; week: number; future: boolean }[] = [];
    for (let i = weeks * 7 - 1; i >= 0; i--) {
      const d = new Date(last);
      d.setDate(last.getDate() - i);
      const idx = weeks * 7 - 1 - i;
      out.push({
        date: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
        day: (d.getDay() + 6) % 7, // Monday first
        week: Math.floor(idx / 7),
        future: d > end,
      });
    }
    return out;
  }, [weeks]);

  const bin = (minutes: number) => (minutes <= 0 ? 0 : minutes < goal / 2 ? 1 : minutes < goal ? 2 : 3);
  const fills = ["var(--paper-2)", "var(--heat-1)", "var(--heat-2)", "var(--heat-3)"];
  const binLabel = ["No practice", `Under ${Math.round(goal / 2)} min`, `${Math.round(goal / 2)}–${goal - 1} min`, `Goal met (${goal}+ min)`];
  const cell = 34;
  const gap = 2; // surface gap, never a stroke
  const W = weeks * (cell + gap);
  const H = 7 * (cell + gap);
  const dayNames = ["M", "T", "W", "T", "F", "S", "S"];

  return (
    <div className="relative" onPointerLeave={() => setTip(null)}>
      <div className="flex gap-2">
        <div className="grid shrink-0 grid-rows-7 text-[10px] text-ink-3" style={{ height: H, rowGap: 0 }} aria-hidden>
          {dayNames.map((n, i) => (
            <span key={i} className="flex items-center" style={{ height: cell + gap }}>
              {n}
            </span>
          ))}
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: W }} className="w-full" role="img" aria-label={`Practice over the last ${weeks} weeks`}>
          {cells.map((c) => {
            const a = byDate.get(c.date);
            const minutes = a?.minutes ?? 0;
            const b = bin(minutes);
            const x = c.week * (cell + gap);
            const yy = c.day * (cell + gap);
            const label = new Date(c.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
            const show = (px: number, py: number) =>
              setTip({ x: px, y: py, title: label, value: c.future ? "—" : `${Math.round(minutes)} min`, detail: c.future ? "Upcoming" : binLabel[b] });
            return (
              <rect
                key={c.date}
                x={x}
                y={yy}
                width={cell}
                height={cell}
                rx="6"
                fill={c.future ? "transparent" : fills[b]}
                stroke={c.future ? "var(--line)" : undefined}
                strokeDasharray={c.future ? "2 3" : undefined}
                tabIndex={c.future ? -1 : 0}
                aria-label={`${label}: ${c.future ? "upcoming" : `${Math.round(minutes)} minutes`}`}
                className="cursor-pointer outline-none transition-opacity hover:opacity-80 focus-visible:opacity-80"
                onPointerMove={(e) => {
                  const box = (e.currentTarget.ownerSVGElement?.parentElement?.parentElement as HTMLElement).getBoundingClientRect();
                  show(e.clientX - box.left, e.clientY - box.top);
                }}
                onFocus={(e) => {
                  const box = (e.currentTarget.ownerSVGElement?.parentElement?.parentElement as HTMLElement).getBoundingClientRect();
                  const own = e.currentTarget.getBoundingClientRect();
                  show(own.left - box.left + own.width / 2, own.top - box.top);
                }}
                onBlur={() => setTip(null)}
              />
            );
          })}
        </svg>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3" aria-label="Legend">
        {fills.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1.5">
            <span className="size-3 rounded-[3px]" style={{ background: f }} aria-hidden />
            {binLabel[i]}
          </span>
        ))}
      </div>
      <Tooltip tip={tip} />
      <DataTable
        caption="Practice by day"
        head={["Date", "Minutes", "Sessions"]}
        rows={cells.filter((c) => !c.future && byDate.has(c.date)).map((c) => [c.date, Math.round(byDate.get(c.date)!.minutes), byDate.get(c.date)!.sessions])}
      />
    </div>
  );
}

// ── score trend (inside a stat tile) ────────────────────────────────────────
export function ScoreSparkline({ scores, height = 56 }: { scores: number[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 240;
  const H = height;
  const pad = 6;
  if (scores.length < 2) return null;
  const xs = (i: number) => pad + (i / (scores.length - 1)) * (W - pad * 2);
  const ys = (v: number) => pad + (1 - v / 100) * (H - pad * 2);
  const line = scores.map((v, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ");
  const area = `${line} L${xs(scores.length - 1)},${H - pad} L${xs(0)},${H - pad} Z`;
  const last = scores.length - 1;
  const active = hover ?? last;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none"
        role="img"
        aria-label={`Score trend over the last ${scores.length} sessions, latest ${scores[last]}`}
        onPointerMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const rel = ((e.clientX - box.left) / box.width) * W;
          // Crosshair snaps to the nearest session: aim at a date, not a 2px line.
          setHover(Math.max(0, Math.min(last, Math.round(((rel - pad) / (W - pad * 2)) * last))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        <path d={area} fill="var(--accent)" opacity="0.1" />
        <path d={line} fill="none" stroke="var(--ink-3)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {hover !== null ? <line x1={xs(hover)} x2={xs(hover)} y1={pad} y2={H - pad} stroke="var(--line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" /> : null}
        {/* End-dot: >= 8px with a 2px surface ring so it survives crossing the line. */}
        <circle cx={xs(active)} cy={ys(scores[active] ?? 0)} r="4" fill="var(--accent)" stroke="var(--card)" strokeWidth="2" />
      </svg>
      <p className="mt-1 text-[12px] text-ink-3" aria-live="polite">
        {hover !== null ? `Session ${hover + 1} of ${scores.length}: ` : "Latest: "}
        <span className="font-semibold text-ink">{scores[active]}</span>
      </p>
      <DataTable caption="Score by session" head={["Session", "Score"]} rows={scores.map((s, i) => [i + 1, s])} />
    </div>
  );
}
