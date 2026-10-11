"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/format";

import { Icon, type IconName } from "./Icon";

type Variant = "primary" | "secondary" | "ghost" | "quiet";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-on-accent shadow-[0_10px_24px_-12px_rgb(var(--glow)/0.7)] hover:brightness-[1.06] active:brightness-95",
  secondary: "bg-card text-ink hairline hover:bg-paper-2",
  ghost: "text-ink-2 hover:bg-paper-2 hover:text-ink",
  quiet: "text-accent-ink hover:bg-accent-soft",
};

export function Button({
  variant = "primary",
  icon,
  iconRight,
  children,
  className,
  size = "md",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  icon?: IconName;
  iconRight?: IconName;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <button
      className={cx(
        "tap inline-flex min-w-0 items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition",
        "disabled:pointer-events-none disabled:opacity-45",
        size === "sm" && "h-10 px-4 text-sm",
        size === "md" && "h-12 px-5 text-[15px]",
        size === "lg" && "h-14 px-7 text-base",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {icon ? <Icon name={icon} size={size === "sm" ? 17 : 19} className="shrink-0" /> : null}
      <span className="truncate">{children}</span>
      {iconRight ? <Icon name={iconRight} size={size === "sm" ? 17 : 19} className="shrink-0" /> : null}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "primary",
  icon,
  iconRight,
  children,
  className,
  size = "md",
}: {
  href: string;
  variant?: Variant;
  icon?: IconName;
  iconRight?: IconName;
  children: ReactNode;
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <Link
      href={href}
      className={cx(
        "tap inline-flex min-w-0 items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition",
        size === "sm" && "h-10 px-4 text-sm",
        size === "md" && "h-12 px-5 text-[15px]",
        size === "lg" && "h-14 px-7 text-base",
        VARIANTS[variant],
        className,
      )}
    >
      {icon ? <Icon name={icon} size={19} className="shrink-0" /> : null}
      <span className="truncate">{children}</span>
      {iconRight ? <Icon name={iconRight} size={19} className="shrink-0" /> : null}
    </Link>
  );
}

export function IconButton({
  icon,
  label,
  className,
  active,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string; active?: boolean }) {
  return (
    <button
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={cx(
        "tap inline-grid place-items-center rounded-full text-ink-2 transition",
        "hover:bg-paper-2 hover:text-ink active:scale-95 disabled:opacity-40",
        active && "bg-accent-soft text-accent-ink",
        className,
      )}
      {...rest}
    >
      <Icon name={icon} size={20} />
    </button>
  );
}

export function Chip({
  selected,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean }) {
  return (
    <button
      aria-pressed={selected}
      className={cx(
        "tap inline-flex shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-medium transition",
        selected ? "bg-ink text-paper" : "bg-card text-ink-2 hairline hover:text-ink",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cx("text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3", className)}>{children}</p>
  );
}

export function Display({ children, className, as: As = "h1" }: { children: ReactNode; className?: string; as?: "h1" | "h2" | "h3" }) {
  return (
    <As className={cx("font-display font-normal tracking-[-0.015em] text-ink balance", className)}>{children}</As>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function Spinner({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={cx("animate-spin", className)} aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity=".2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
