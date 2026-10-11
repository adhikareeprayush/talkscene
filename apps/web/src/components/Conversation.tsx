"use client";

import type { GoalState, Lang } from "@talkscene/sdk";
import { useMemo, useState } from "react";

import { cx } from "@/lib/format";
import type { LiveTurn } from "@/lib/store/session";

import { Icon } from "./Icon";

/** Word segmentation that works for Japanese and Korean, not just spaced scripts. */
function segment(text: string, lang: Lang): { text: string; word: boolean }[] {
  const Seg = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (Seg) {
    const segmenter = new Seg(lang, { granularity: "word" });
    return Array.from(segmenter.segment(text), (s) => ({ text: s.segment, word: Boolean(s.isWordLike) }));
  }
  return text.split(/(\s+|[.,!?。、！？])/).filter(Boolean).map((t) => ({ text: t, word: /\w|[぀-ヿ一-鿿가-힯]/.test(t) }));
}

/** Tappable target-language text: every word opens the explain popover. */
export function TapText({
  text,
  lang,
  onWord,
  className,
}: {
  text: string;
  lang: Lang;
  onWord?: (word: string) => void;
  className?: string;
}) {
  const parts = useMemo(() => segment(text, lang), [text, lang]);
  if (!onWord) return <span lang={lang} className={cx("target", className)}>{text}</span>;
  return (
    <span lang={lang} className={cx("target", className)}>
      {parts.map((part, i) =>
        part.word ? (
          <button
            key={i}
            type="button"
            onClick={() => onWord(part.text)}
            // `inline`, not the button default of inline-block: an inline-block
            // creates a break opportunity around every word, which defeats
            // keep-all and strands punctuation ("괜찮으세요" / "?") on its own line.
            className="inline rounded-[4px] decoration-accent/40 decoration-[1.5px] underline-offset-[5px] transition hover:bg-accent-soft hover:underline focus-visible:bg-accent-soft"
          >
            {part.text}
          </button>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

export function ChatBubble({
  turn,
  lang,
  persona,
  showTranslation,
  showRomanization,
  onReplay,
  onSlow,
  onWord,
  onTranslate,
  playing,
}: {
  turn: LiveTurn;
  lang: Lang;
  persona: string;
  showTranslation: boolean;
  showRomanization: boolean;
  onReplay?: () => void;
  onSlow?: () => void;
  onWord?: (word: string) => void;
  onTranslate?: () => void;
  playing?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const [understood, setUnderstood] = useState(false);

  if (turn.role === "user") {
    const unclear = (turn.words ?? []).filter((w) => w.prob < 0.6);
    return (
      <div className="bubble-in flex justify-end pl-10">
        <div className="max-w-[85%]">
          <div
            className={cx(
              "rounded-[var(--radius-bubble)] rounded-br-md bg-ink px-4 py-3 text-paper",
              turn.optimistic && "opacity-60",
            )}
          >
            <p lang={lang} className={cx("target text-[17px]", turn.optimistic && "animate-pulse")}>
              {turn.text || "…"}
            </p>
          </div>
          {!turn.optimistic && turn.words && turn.words.length > 0 ? (
            <div className="mt-1 flex justify-end">
              <button
                onClick={() => setUnderstood((v) => !v)}
                className="tap inline-flex items-center gap-1 rounded-full px-2 text-[12px] text-ink-3 hover:text-ink-2"
                aria-expanded={understood}
              >
                <Icon name="eye" size={14} /> How it was heard
              </button>
            </div>
          ) : null}
          {understood ? (
            <div className="fade-in mt-1 rounded-2xl bg-paper-2 px-3 py-2 text-[13px] text-ink-2">
              <p lang={lang} className="target">
                {(turn.words ?? []).map((w, i) => (
                  <span
                    key={i}
                    className={cx(w.prob < 0.6 && "underline decoration-improve decoration-wavy underline-offset-4")}
                    title={w.prob < 0.6 ? "This word may have been unclear (estimate)" : undefined}
                  >
                    {w.w}
                    {lang === "ko" || lang === "ja" ? "" : " "}
                  </span>
                ))}
              </p>
              {unclear.length ? (
                <p className="mt-1 text-[12px] text-ink-3">
                  Wavy words may have been unclear — an estimate from speech recognition, not a score.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  const showTrans = (showTranslation || revealed) && turn.translation;
  return (
    <div className="bubble-in flex gap-3 pr-6">
      <div
        aria-hidden
        className={cx(
          "mt-1 grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft font-display text-[15px] text-accent-ink transition",
          playing && "ring-2 ring-accent ring-offset-2 ring-offset-paper",
        )}
      >
        {persona.slice(0, 1)}
      </div>
      <div className="min-w-0 max-w-[88%]">
        <div className="rounded-[var(--radius-bubble)] rounded-tl-md bg-card px-4 py-3 hairline">
          <p className={cx("text-[19px] leading-relaxed text-ink", turn.streaming && "typing-caret")}>
            <TapText text={turn.text} lang={lang} onWord={turn.streaming ? undefined : onWord} />
          </p>
          {showRomanization && turn.romanization ? (
            <p className="mt-1 text-[13px] italic leading-snug text-ink-3">{turn.romanization}</p>
          ) : null}
          {showTrans ? (
            <p className="fade-in mt-2 border-t border-line pt-2 text-[14px] leading-snug text-ink-2">{turn.translation}</p>
          ) : null}
        </div>
        {!turn.streaming ? (
          <div className="mt-1 flex items-center gap-0.5 text-ink-3">
            <button onClick={onReplay} className="tap inline-grid place-items-center rounded-full hover:bg-paper-2 hover:text-ink" aria-label="Replay">
              <Icon name="speaker" size={18} />
            </button>
            <button onClick={onSlow} className="tap inline-grid place-items-center rounded-full hover:bg-paper-2 hover:text-ink" aria-label="Replay slowly">
              <Icon name="turtle" size={19} />
            </button>
            {!showTranslation ? (
              <button
                onClick={() => {
                  if (!turn.translation) onTranslate?.();
                  setRevealed((v) => !v);
                }}
                className="tap inline-flex items-center gap-1 rounded-full px-2 text-[12px] font-medium hover:bg-paper-2 hover:text-ink"
                aria-expanded={revealed}
              >
                <Icon name="translate" size={16} /> {revealed ? "Hide" : "Translate"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function TurnProgress({ used, target }: { used: number; target: number }) {
  return (
    <div className="flex items-center gap-2" aria-label={`Turn ${used} of ${target}`}>
      <span className="tabular text-[12px] font-medium text-ink-3">
        {used}/{target}
      </span>
      <div className="flex gap-[3px]" aria-hidden>
        {Array.from({ length: target }, (_, i) => (
          <span
            key={i}
            className={cx(
              "h-1.5 w-2.5 rounded-full transition-colors duration-500",
              i < used ? "bg-accent" : i === used ? "bg-accent/35" : "bg-line-strong",
            )}
          />
        ))}
      </div>
    </div>
  );
}

export function GoalChecklist({
  goals,
  compact,
  className,
}: {
  goals: GoalState[];
  compact?: boolean;
  className?: string;
}) {
  const done = goals.filter((g) => g.done).length;
  if (compact) {
    return (
      <div className={cx("flex items-center gap-1.5 overflow-x-auto scrollbar-none", className)} aria-label={`${done} of ${goals.length} goals done`}>
        {goals.map((goal) => (
          <span
            key={goal.id}
            title={goal.text}
            className={cx(
              "inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors duration-500",
              goal.done ? "bg-great-soft text-great" : "bg-paper-2 text-ink-3",
            )}
          >
            <Icon name={goal.done ? "check" : "target"} size={13} />
            <span className="max-w-[9rem] truncate">{goal.text}</span>
          </span>
        ))}
      </div>
    );
  }
  return (
    <ul className={cx("space-y-2", className)}>
      {goals.map((goal) => (
        <li key={goal.id} className="flex items-start gap-3">
          <span
            className={cx(
              "mt-0.5 grid size-5 shrink-0 place-items-center rounded-md transition-colors duration-500",
              goal.done ? "bg-great text-paper" : "ring-1 ring-inset ring-line-strong",
            )}
            aria-hidden
          >
            {goal.done ? <Icon name="check" size={13} strokeWidth={2.5} /> : null}
          </span>
          <span className={cx("text-[15px]", goal.done ? "text-ink-2 line-through decoration-ink-3/40" : "text-ink")}>
            {goal.text}
            <span className="sr-only">{goal.done ? " (done)" : " (not yet)"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
