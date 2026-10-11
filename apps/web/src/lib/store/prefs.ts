"use client";

/**
 * Per-device conveniences: the language being studied and the theme.
 *
 * These live in localStorage because they must apply *before* the first API
 * response (the accent colour is visible on first paint). Anything that matters
 * across devices is on the account (`PATCH /v1/me`) instead. Every storage
 * access is guarded: private mode and blocked storage must not break the app.
 */

import type { Lang, Level } from "@talkscene/sdk";
import { create } from "zustand";

import { applyLang, applyTheme } from "../lang";

export const PREFS_KEY = "talkscene.prefs";

type Prefs = {
  lang: Lang | null;
  level: Level;
  theme: "system" | "light" | "dark";
  onboarded: boolean;
  dailyGoal: number;
};

const DEFAULTS: Prefs = { lang: null, level: "A2", theme: "system", onboarded: false, dailyGoal: 10 };

function read(): Prefs {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Prefs>) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

function write(prefs: Prefs) {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable: preferences last for this tab only */
  }
}

type Store = Prefs & {
  hydrated: boolean;
  hydrate(): void;
  set(patch: Partial<Prefs>): void;
};

export const usePrefs = create<Store>((set, get) => ({
  ...DEFAULTS,
  hydrated: false,
  hydrate() {
    // No DOM writes here: PREFS_BOOT_SCRIPT already applied the stored
    // language and theme before first paint. Re-applying would clobber a page
    // that set its own language, because child effects run before this one.
    set({ ...read(), hydrated: true });
  },
  set(patch) {
    const next: Prefs = {
      lang: patch.lang !== undefined ? patch.lang : get().lang,
      level: patch.level ?? get().level,
      theme: patch.theme ?? get().theme,
      onboarded: patch.onboarded ?? get().onboarded,
      dailyGoal: patch.dailyGoal ?? get().dailyGoal,
    };
    if (patch.lang !== undefined) applyLang(next.lang);
    if (patch.theme) applyTheme(next.theme);
    write(next);
    set(next);
  },
}));

/**
 * Runs inline in <head> before React: sets data-lang / data-theme from storage
 * so the first paint already wears the right accent. Kept tiny and defensive.
 */
export const PREFS_BOOT_SCRIPT = `(function(){try{var p=JSON.parse(localStorage.getItem(${JSON.stringify(PREFS_KEY)})||"{}");var d=document.documentElement;if(p.lang)d.dataset.lang=p.lang;if(p.theme&&p.theme!=="system")d.dataset.theme=p.theme;}catch(e){}})();`;
