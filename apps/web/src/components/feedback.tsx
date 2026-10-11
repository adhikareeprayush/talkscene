"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/lib/format";

import { Icon, type IconName } from "./Icon";
import { Button } from "./ui";

/** Calm empty states (plan §11.1): say what this is for and how to fill it. */
export function EmptyState({
  icon = "sparkle",
  title,
  body,
  action,
}: {
  icon?: IconName;
  title: string;
  body?: ReactNode;
  action?: { label: string; href?: string; onClick?: () => void };
}) {
  return (
    <div className="card reveal flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-4 grid size-14 place-items-center rounded-2xl bg-accent-soft text-accent-ink">
        <Icon name={icon} size={26} />
      </div>
      <h3 className="font-display text-2xl text-ink">{title}</h3>
      {body ? <p className="mt-2 max-w-sm text-[15px] text-ink-2 pretty">{body}</p> : null}
      {action ? (
        <div className="mt-6">
          {action.href ? (
            <Link href={action.href} className="tap inline-flex h-12 items-center rounded-full bg-accent px-5 font-medium text-on-accent">
              {action.label}
            </Link>
          ) : (
            <Button onClick={action.onClick}>{action.label}</Button>
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Errors with a way forward (plan §11.4 "ErrorBanner (with retry/fallback)").
 * Never red-alarm styling: the tone is "here is what to do", not "you failed".
 */
export function ErrorBanner({
  message,
  onRetry,
  fallback,
  tone = "attention",
  className,
}: {
  message: string;
  onRetry?: () => void;
  fallback?: { label: string; onClick: () => void };
  tone?: "attention" | "improve" | "info";
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cx(
        "fade-in flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl px-4 py-3 text-[14px]",
        tone === "attention" && "bg-attention-soft text-attention",
        tone === "improve" && "bg-improve-soft text-improve",
        tone === "info" && "bg-paper-2 text-ink-2",
        className,
      )}
    >
      <Icon name={tone === "info" ? "info" : "alert"} size={18} className="shrink-0" />
      <p className="min-w-0 flex-1 pretty">{message}</p>
      <div className="flex gap-2">
        {fallback ? (
          <button onClick={fallback.onClick} className="tap rounded-full px-3 text-sm font-medium underline-offset-4 hover:underline">
            {fallback.label}
          </button>
        ) : null}
        {onRetry ? (
          <button onClick={onRetry} className="tap inline-flex items-center gap-1.5 rounded-full bg-card/70 px-3 text-sm font-medium">
            <Icon name="retry" size={16} /> Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Score-band badge. Colour is never the only signal: icon + word always ride along. */
export function BandBadge({ score, className }: { score: number | null | undefined; className?: string }) {
  const value = score ?? 0;
  const band = score == null ? "none" : value >= 85 ? "great" : value >= 60 ? "improve" : "attention";
  const styles = {
    great: "bg-great-soft text-great",
    improve: "bg-improve-soft text-improve",
    attention: "bg-attention-soft text-attention",
    none: "bg-paper-2 text-ink-3",
  }[band];
  const label = { great: "Great", improve: "Improving", attention: "Focus", none: "—" }[band];
  const icon: IconName = band === "great" ? "check" : band === "none" ? "info" : "target";
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", styles, className)}>
      <Icon name={icon} size={12} />
      {label}
    </span>
  );
}

export function LevelBadge({ level, className }: { level: string; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex h-6 items-center rounded-md px-1.5 font-mono text-[11px] font-semibold tracking-wide text-accent-ink ring-1 ring-inset ring-accent/30",
        className,
      )}
      title={`CEFR level ${level}`}
    >
      {level}
    </span>
  );
}
