"use client";

import type { Correction, DrillAttempt, Lang, SrsCard } from "@talkscene/sdk";
import { useState } from "react";

import { band, BAND_LABEL, cx } from "@/lib/format";

import { Icon } from "./Icon";
import { Button } from "./ui";

/** "You said -> Better -> Why" (plan §8.2). Amber framing, never a red X. */
export function CorrectionCard({
  correction,
  lang,
  onHear,
  onSave,
  saved,
  index = 0,
}: {
  correction: Correction;
  lang: Lang;
  onHear?: (text: string) => void;
  onSave?: () => void;
  saved?: boolean;
  index?: number;
}) {
  return (
    <article className="card reveal p-5" style={{ ["--i" as string]: index }}>
      <div className="flex items-center justify-between gap-2">
        <span className="rounded-full bg-improve-soft px-2.5 py-0.5 text-[11px] font-semibold capitalize text-improve">
          {correction.category.replace("-", " ")}
        </span>
        {correction.turn != null ? <span className="text-[12px] text-ink-3">Turn {correction.turn}</span> : null}
      </div>
      <dl className="mt-3 space-y-3">
        <div>
          <dt className="text-[12px] font-medium text-ink-3">You said</dt>
          <dd lang={lang} className="target mt-0.5 text-[17px] text-ink-2">
            {correction.said}
          </dd>
        </div>
        <div className="relative pl-3">
          <span className="absolute inset-y-1 left-0 w-[3px] rounded-full bg-accent" aria-hidden />
          <dt className="text-[12px] font-medium text-accent-ink">More natural</dt>
          <dd lang={lang} className="target mt-0.5 text-[19px] font-medium text-ink">
            {correction.better}
          </dd>
        </div>
        {correction.why ? (
          <div>
            <dt className="sr-only">Why</dt>
            <dd className="text-[14px] leading-relaxed text-ink-2 pretty">{correction.why}</dd>
          </div>
        ) : null}
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        {onHear ? (
          <Button size="sm" variant="secondary" icon="speaker" onClick={() => onHear(correction.better)}>
            Hear it
          </Button>
        ) : null}
        {onSave ? (
          <Button size="sm" variant={saved ? "quiet" : "secondary"} icon={saved ? "check" : "bookmark"} onClick={onSave} disabled={saved}>
            {saved ? "Saved" : "Save to flashcards"}
          </Button>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Per-word pronunciation result (plan §11.3 G). Colour bands follow the plan
 * (>=85 green, 60-84 amber, <60 coral) and always carry an icon and a word.
 * When the attempt was scored by the heuristic fallback there is no phoneme
 * data, and the strip says so instead of drawing one (ADR 0003).
 */
export function PhonemeStrip({ attempt, lang }: { attempt: DrillAttempt; lang: Lang }) {
  const [open, setOpen] = useState<number | null>(null);
  const words = attempt.words ?? [];
  return (
    <div>
      <div className="flex flex-wrap gap-1.5" lang={lang}>
        {words.map((word, i) => {
          const b = band(word.accuracy);
          const style = {
            great: "bg-great-soft text-great",
            improve: "bg-improve-soft text-improve",
            attention: "bg-attention-soft text-attention",
          }[b];
          const hasPhonemes = attempt.authoritative && word.phonemes.length > 0;
          return (
            <button
              key={i}
              onClick={() => hasPhonemes && setOpen(open === i ? null : i)}
              aria-expanded={hasPhonemes ? open === i : undefined}
              aria-label={`${word.word}: ${Math.round(word.accuracy)}, ${BAND_LABEL[b]}`}
              className={cx("tap target inline-flex items-center gap-1 rounded-xl px-3 text-[17px] font-medium", style, !hasPhonemes && "cursor-default")}
            >
              {word.word}
              <Icon name={b === "great" ? "check" : "target"} size={13} />
            </button>
          );
        })}
      </div>
      {open !== null && words[open] ? (
        <div className="fade-in mt-3 rounded-2xl bg-paper-2 p-3">
          <p className="text-[12px] font-medium text-ink-3">Sounds in “{words[open]!.word}”</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {words[open]!.phonemes.map((p, j) => (
              <span key={j} className={cx("rounded-lg px-2 py-1 font-mono text-[13px]", band(p.score) === "great" ? "bg-great-soft text-great" : band(p.score) === "improve" ? "bg-improve-soft text-improve" : "bg-attention-soft text-attention")}>
                /{p.phoneme}/ <span className="opacity-75">{Math.round(p.score)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {!attempt.authoritative ? (
        <p className="mt-3 flex items-start gap-1.5 text-[12px] text-ink-3">
          <Icon name="info" size={14} className="mt-0.5 shrink-0" />
          Estimated from speech recognition — phoneme scoring is not available, so these show which words came through, not how they sounded.
        </p>
      ) : null}
    </div>
  );
}

const RATINGS: { rating: 1 | 2 | 3 | 4; label: string; key: "again" | "hard" | "good" | "easy" }[] = [
  { rating: 1, label: "Again", key: "again" },
  { rating: 2, label: "Hard", key: "hard" },
  { rating: 3, label: "Good", key: "good" },
  { rating: 4, label: "Easy", key: "easy" },
];

/** Front: word + audio. Back: meaning and the sentence from *your* conversation (plan §11.3 I). */
export function FlashCard({
  card,
  onRate,
  onHear,
  busy,
}: {
  card: SrsCard;
  onRate: (rating: 1 | 2 | 3 | 4) => void;
  onHear: (text: string) => void;
  busy?: boolean;
}) {
  const [flipped, setFlipped] = useState(false);
  const lang = card.vocab.language as Lang;
  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => setFlipped((v) => !v)}
        aria-label={flipped ? "Show the word" : "Reveal the meaning"}
        className="card relative min-h-[18rem] w-full p-6 text-center transition-transform duration-500 [perspective:1200px]"
      >
        {!flipped ? (
          <div className="fade-in flex h-full min-h-[15rem] flex-col items-center justify-center">
            <p lang={lang} className="target text-[40px] font-medium leading-tight text-ink">
              {card.vocab.term}
            </p>
            {card.vocab.reading ? <p className="mt-2 text-[15px] text-ink-3">{card.vocab.reading}</p> : null}
            <p className="mt-8 text-[13px] text-ink-3">Tap to reveal</p>
          </div>
        ) : (
          <div className="fade-in flex h-full min-h-[15rem] flex-col items-center justify-center">
            <p lang={lang} className="target text-[22px] text-ink-2">
              {card.vocab.term}
            </p>
            <p className="mt-3 font-display text-[30px] leading-tight text-ink">{card.vocab.meaning}</p>
            {card.vocab.example ? (
              <p lang={lang} className="target mt-5 max-w-sm rounded-2xl bg-paper-2 px-4 py-3 text-[15px] text-ink-2">
                “{card.vocab.example}”
              </p>
            ) : null}
          </div>
        )}
      </button>
      <div className="flex justify-center">
        <Button variant="ghost" size="sm" icon="speaker" onClick={() => onHear(card.vocab.term)}>
          Hear it
        </Button>
      </div>
      {flipped ? (
        <div className="fade-in grid grid-cols-4 gap-2" role="group" aria-label="How well did you remember it?">
          {RATINGS.map((r) => (
            <button
              key={r.rating}
              disabled={busy}
              onClick={() => {
                setFlipped(false);
                onRate(r.rating);
              }}
              className={cx(
                "tap flex flex-col items-center justify-center rounded-2xl py-2.5 text-[14px] font-semibold transition disabled:opacity-50",
                r.rating === 1 && "bg-attention-soft text-attention",
                r.rating === 2 && "bg-improve-soft text-improve",
                r.rating === 3 && "bg-great-soft text-great",
                r.rating === 4 && "bg-accent-soft text-accent-ink",
              )}
            >
              {r.label}
              <span className="text-[11px] font-medium opacity-75">{card.intervals[r.key] ?? ""}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
