"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useStatus } from "@/lib/api";
import { cx } from "@/lib/format";

import { Icon, type IconName } from "./Icon";

const NAV: { href: string; label: string; icon: IconName; match: RegExp }[] = [
  { href: "/home", label: "Home", icon: "home", match: /^\/home/ },
  { href: "/scenarios", label: "Scenarios", icon: "grid", match: /^\/(scenarios|create)/ },
  { href: "/vocab", label: "Vocab", icon: "cards", match: /^\/vocab/ },
  { href: "/progress", label: "Progress", icon: "chart", match: /^\/(progress|history)/ },
  { href: "/settings", label: "Me", icon: "user", match: /^\/settings/ },
];

/**
 * Screens that own the viewport. Each has a back button and its own fixed
 * primary action at the bottom, which the nav bar would otherwise sit on top
 * of (plan §11.1: one primary action per screen).
 */
const IMMERSIVE = [
  /^\/$/,
  /^\/onboarding/,
  /^\/scenarios\/[^/]+$/,
  /^\/session\/[^/]+$/,
  /^\/session\/[^/]+\/(report|drills)/,
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const immersive = IMMERSIVE.some((re) => re.test(pathname));

  return (
    <div className="relative z-10 flex min-h-dvh flex-col">
      <StatusBanner />
      <main className={cx("flex-1", !immersive && "pb-28 md:pb-12")} id="main">
        {children}
      </main>
      {!immersive ? <BottomNav pathname={pathname} /> : null}
    </div>
  );
}

/**
 * Bottom nav on phones; a quiet top rail on desktop (plan §11.3 B).
 * Labels are always visible — icon-only navigation fails a first-time learner.
 */
function BottomNav({ pathname }: { pathname: string }) {
  return (
    <nav
      aria-label="Primary"
      className={cx(
        "fixed inset-x-0 bottom-0 z-30 safe-bottom md:sticky md:top-0 md:bottom-auto md:order-first",
        "border-t border-line bg-paper/85 backdrop-blur-xl md:border-t-0 md:border-b",
      )}
    >
      <ul className="mx-auto grid max-w-md grid-cols-5 px-2 md:flex md:max-w-5xl md:justify-end md:gap-1 md:px-6 md:py-2">
        <li className="hidden md:mr-auto md:flex md:items-center">
          <Link href="/home" className="font-display text-xl tracking-tight text-ink">
            TalkScene
          </Link>
        </li>
        {NAV.map((item) => {
          const active = item.match.test(pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "tap flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition md:flex-row md:gap-2 md:rounded-full md:px-4 md:text-sm",
                  active ? "text-accent-ink md:bg-accent-soft" : "text-ink-3 hover:text-ink",
                )}
              >
                <Icon name={item.icon} size={22} />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/**
 * Degradation is shown, never hidden (plan §16 runbook): a learner hearing a
 * robotic browser voice deserves to know why.
 */
function StatusBanner() {
  const { data } = useStatus();
  if (!data || data.status === "ok" || !data.message) return null;
  const placeholder = data.degraded.some((d) => d.endsWith(":placeholder"));
  return (
    <div
      role="status"
      className={cx(
        "relative z-40 flex items-center justify-center gap-2 px-4 py-2 text-center text-[13px]",
        placeholder ? "bg-paper-2 text-ink-2" : "bg-improve-soft text-improve",
      )}
    >
      <Icon name="info" size={16} className="shrink-0" />
      <span className="pretty">
        {placeholder ? "Demo mode — no AI provider keys are configured, so replies are placeholders." : data.message}
      </span>
    </div>
  );
}

export function TopBar({
  title,
  back,
  trailing,
  subtitle,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  back?: string | (() => void);
  trailing?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-line/70 bg-paper/85 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-3xl items-center gap-2 px-2">
        {back ? (
          typeof back === "string" ? (
            <Link href={back} aria-label="Back" className="tap grid place-items-center rounded-full text-ink-2 hover:bg-paper-2">
              <Icon name="back" size={22} />
            </Link>
          ) : (
            <button onClick={back} aria-label="Back" className="tap grid place-items-center rounded-full text-ink-2 hover:bg-paper-2">
              <Icon name="back" size={22} />
            </button>
          )
        ) : (
          <span className="w-2" />
        )}
        <div className="min-w-0 flex-1">
          {title ? <h1 className="truncate text-[15px] font-semibold text-ink">{title}</h1> : null}
          {subtitle ? <p className="truncate text-xs text-ink-3">{subtitle}</p> : null}
        </div>
        {trailing}
      </div>
    </header>
  );
}

export function Page({ children, className, wide }: { children: ReactNode; className?: string; wide?: boolean }) {
  return (
    <div className={cx("mx-auto w-full px-5 pt-6 md:pt-10", wide ? "max-w-5xl" : "max-w-3xl", className)}>
      {children}
    </div>
  );
}
