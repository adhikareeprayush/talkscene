import type { Lang, Level } from "@talkscene/sdk";

export type LangMeta = {
  code: Lang;
  name: string;
  native: string;
  /**
   * A glyph in the language's own script, used as its mark. Not a flag: flag
   * emoji never render on Windows, and a flag names a country, not a language
   * (whose English? whose German?).
   */
  mark: string;
  /** BCP-47 tag for the Web Speech APIs (recognition and synthesis). */
  bcp47: string;
  accentName: string;
  /** A greeting shown on the language picker, in the language itself. */
  hello: string;
  cjk: boolean;
};

export const LANGS: Record<Lang, LangMeta> = {
  ko: { code: "ko", name: "Korean", native: "한국어", mark: "한", bcp47: "ko-KR", accentName: "coral", hello: "안녕하세요", cjk: true },
  ja: { code: "ja", name: "Japanese", native: "日本語", mark: "あ", bcp47: "ja-JP", accentName: "indigo", hello: "こんにちは", cjk: true },
  de: { code: "de", name: "German", native: "Deutsch", mark: "De", bcp47: "de-DE", accentName: "amber", hello: "Hallo", cjk: false },
  en: { code: "en", name: "English", native: "English", mark: "En", bcp47: "en-US", accentName: "teal", hello: "Hello", cjk: false },
};

export const LANG_ORDER: Lang[] = ["ko", "ja", "de", "en"];

export const LEVELS: { level: Level; label: string; plain: string; detail: string }[] = [
  { level: "A1", label: "Beginner", plain: "Never studied", detail: "Short sentences, everyday words, slower speech." },
  { level: "A2", label: "Elementary", plain: "Know the basics", detail: "Simple conversations about familiar things." },
  { level: "B1", label: "Intermediate", plain: "Can chat a bit", detail: "Natural pace, follow-up questions, small surprises." },
  { level: "B2", label: "Upper-intermediate", plain: "Comfortable", detail: "Fully natural speech, indirectness, register shifts." },
];

export const CATEGORIES = [
  { id: "travel", label: "Travel", icon: "✈️" },
  { id: "food", label: "Food", icon: "🍜" },
  { id: "shopping", label: "Shopping", icon: "🛍️" },
  { id: "health", label: "Health", icon: "🩺" },
  { id: "services", label: "Services", icon: "🗂️" },
  { id: "social", label: "Social", icon: "💬" },
  { id: "work", label: "Work", icon: "💼" },
  { id: "culture", label: "Culture", icon: "🏮" },
] as const;

export function isLang(value: unknown): value is Lang {
  return value === "ko" || value === "ja" || value === "de" || value === "en";
}

/** Tint the whole app for a language (see globals.css). */
export function applyLang(lang: Lang | null) {
  if (typeof document === "undefined") return;
  if (lang) document.documentElement.dataset.lang = lang;
  else delete document.documentElement.dataset.lang;
}

export function applyTheme(theme: "system" | "light" | "dark") {
  if (typeof document === "undefined") return;
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

export function titleFor(title: Record<string, string> | undefined, lang: Lang): { target?: string; en: string } {
  const en = title?.en ?? "";
  const target = lang !== "en" ? title?.[lang] : undefined;
  return { target, en };
}
