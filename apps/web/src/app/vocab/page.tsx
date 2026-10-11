"use client";

import type { Lang } from "@talkscene/sdk";
import Link from "next/link";
import { useSessionInfo } from "@/lib/client-state";
import { useState } from "react";

import { Page } from "@/components/AppShell";
import { EmptyState, ErrorBanner } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { FlashCard } from "@/components/learning";
import { Button, Chip, Display, Skeleton } from "@/components/ui";
import { problemMessage, useDueCards, useReview, useSaveWord, useVocab } from "@/lib/api";
import { speak } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { LANG_ORDER, LANGS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

export default function Vocab() {
  const prefs = usePrefs();
  const [lang, setLang] = useState<Lang | undefined>(prefs.lang ?? undefined);
  const [mode, setMode] = useState<"review" | "list">("review");
  const { guest } = useSessionInfo();
  const due = useDueCards(lang);
  const vocab = useVocab(lang);
  const review = useReview();
  const [reviewed, setReviewed] = useState(0);

  if (guest) {
    return (
      <Page>
        <Display className="reveal text-[38px]">Vocabulary</Display>
        <div className="mt-8">
          <EmptyState icon="cards" title="Keep the words you meet" body="Tap any word in a conversation to save it. Your flashcards use the sentence you actually heard, and spaced repetition brings each one back right before you forget it." action={{ label: "Create a free account", href: "/settings#account" }} />
        </div>
      </Page>
    );
  }

  const cards = due.data ?? [];
  const current = cards[0];

  return (
    <Page>
      <div className="flex items-end justify-between gap-3">
        <Display className="reveal text-[38px]">Vocabulary</Display>
        <div role="tablist" className="flex rounded-full bg-paper-2 p-1">
          {(["review", "list"] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)} className={cx("tap rounded-full px-4 text-[13px] font-semibold capitalize", mode === m ? "bg-card text-ink shadow-sm" : "text-ink-3")}>
              {m === "review" ? `Review${cards.length ? ` · ${cards.length}` : ""}` : "All words"}
            </button>
          ))}
        </div>
      </div>
      <div className="-mx-5 mt-5 flex gap-2 overflow-x-auto px-5 scrollbar-none">
        <Chip selected={!lang} onClick={() => setLang(undefined)}>All</Chip>
        {LANG_ORDER.map((code) => (
          <Chip key={code} selected={lang === code} onClick={() => setLang(code)}><LangMark lang={code} size="xs" /> {LANGS[code].name}</Chip>
        ))}
      </div>

      {mode === "review" ? (
        <section className="mt-8">
          {due.isLoading ? (
            <Skeleton className="h-80" />
          ) : due.error ? (
            <ErrorBanner message={problemMessage(due.error)} onRetry={() => void due.refetch()} />
          ) : current ? (
            <div className="mx-auto max-w-md" data-lang={current.vocab.language}>
              <p className="mb-3 text-center text-[13px] text-ink-3">{cards.length} due{reviewed ? ` · ${reviewed} done this session` : ""}</p>
              <FlashCard
                key={current.card_id}
                card={current}
                busy={review.isPending}
                onHear={(text) => void speak(text, current.vocab.language as Lang)}
                onRate={(rating) =>
                  review.mutate(
                    { cardId: current.card_id, rating },
                    { onSuccess: () => { setReviewed((n) => n + 1); void due.refetch(); } },
                  )
                }
              />
              {review.error ? <ErrorBanner className="mt-3" message={problemMessage(review.error)} /> : null}
            </div>
          ) : (
            <EmptyState icon="check" title={reviewed ? "All caught up" : "Nothing due right now"} body={reviewed ? `You reviewed ${reviewed} card${reviewed === 1 ? "" : "s"}. They will come back when you are about to forget them.` : "New words arrive from your conversations. Come back later, or add one below."} action={{ label: "Browse all words", onClick: () => setMode("list") }} />
          )}
        </section>
      ) : (
        <WordList lang={lang} loading={vocab.isLoading} items={vocab.data?.items ?? []} />
      )}
    </Page>
  );
}

function WordList({ lang, loading, items }: { lang?: Lang; loading: boolean; items: { id: string; term: string; meaning: string; reading?: string | null; language: string; example?: string | null; source_session_id?: string | null; state?: string | null }[] }) {
  const save = useSaveWord();
  const [term, setTerm] = useState("");
  const [meaning, setMeaning] = useState("");
  const [addLang, setAddLang] = useState<Lang>(lang ?? usePrefs.getState().lang ?? "ko");

  return (
    <section className="mt-8 space-y-6">
      <form
        className="card grid gap-2 p-4 sm:grid-cols-[auto_1fr_1fr_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          if (!term.trim() || !meaning.trim()) return;
          save.mutate({ language: addLang, term: term.trim(), meaning: meaning.trim() }, { onSuccess: () => { setTerm(""); setMeaning(""); } });
        }}
      >
        <select aria-label="Language" value={addLang} onChange={(e) => setAddLang(e.target.value as Lang)} className="tap rounded-full bg-paper-2 px-3 text-[14px] text-ink outline-none">
          {LANG_ORDER.map((c) => <option key={c} value={c}>{LANGS[c].name}</option>)}
        </select>
        <input lang={addLang} aria-label="Word" placeholder="Word or phrase" value={term} onChange={(e) => setTerm(e.target.value)} className="target tap rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-ink-3" />
        <input aria-label="Meaning" placeholder="Meaning" value={meaning} onChange={(e) => setMeaning(e.target.value)} className="tap rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-ink-3" />
        <Button type="submit" size="sm" icon="plus" disabled={save.isPending}>Add</Button>
      </form>
      {loading ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <EmptyState icon="cards" title="No saved words yet" body="Tap any word in a conversation, or add one above." />
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-[18px] bg-card hairline">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 p-4">
              <button onClick={() => void speak(item.term, item.language as Lang)} aria-label={`Hear ${item.term}`} className="tap -ml-2 grid shrink-0 place-items-center rounded-full text-ink-3 hover:text-accent-ink">
                <Icon name="speaker" size={18} />
              </button>
              <div className="min-w-0 flex-1">
                <p lang={item.language} className="target text-[18px] text-ink">
                  {item.term} {item.reading ? <span className="text-[13px] text-ink-3">{item.reading}</span> : null}
                </p>
                <p className="text-[14px] text-ink-2">{item.meaning}</p>
                {item.example ? <p lang={item.language} className="target mt-1 text-[13px] text-ink-3">“{item.example}”</p> : null}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1 text-[11px] text-ink-3">
                <LangMark lang={item.language as Lang} size="xs" />
                {item.state ? <span className="capitalize">{item.state}</span> : null}
                {item.source_session_id ? <Link href={`/session/${item.source_session_id}/report`} className="text-accent-ink hover:underline">from a session</Link> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
