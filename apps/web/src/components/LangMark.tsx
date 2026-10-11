import type { Lang } from "@talkscene/sdk";

import { cx } from "@/lib/format";
import { LANGS } from "@/lib/lang";

/**
 * A language's mark: its own script in its own accent. Scoped with
 * `data-lang`, so it stays correctly tinted inside a page of another language.
 */
export function LangMark({ lang, size = "sm", className }: { lang: Lang; size?: "xs" | "sm" | "md" | "lg"; className?: string }) {
  const meta = LANGS[lang];
  return (
    <span
      data-lang={lang}
      aria-hidden
      className={cx(
        "inline-grid shrink-0 place-items-center bg-accent-soft font-semibold leading-none text-accent-ink",
        meta.cjk ? "target" : "tracking-tight",
        size === "xs" && "size-5 rounded-[6px] text-[10px]",
        size === "sm" && "size-6 rounded-[7px] text-[11px]",
        size === "md" && "size-9 rounded-[10px] text-[15px]",
        size === "lg" && "size-12 rounded-[14px] text-[20px]",
        className,
      )}
    >
      {meta.mark}
    </span>
  );
}
