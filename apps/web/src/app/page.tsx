"use client";

import type { Lang } from "@talkscene/sdk";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { applyLang, LANG_ORDER, LANGS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

/** One authored exchange per language, lifted from the shipped scenario packs. */
const SAMPLES: Record<Lang, { scene: string; persona: string; ai: string; aiEn: string; you: string }> = {
  ko: { scene: "Hotel check-in · Seoul", persona: "민지", ai: "안녕하세요, 어서 오세요. 예약하셨어요?", aiEn: "Hello, welcome. Do you have a reservation?", you: "네, 김민수로 예약했어요." },
  ja: { scene: "Konbini · Tokyo", persona: "田中", ai: "いらっしゃいませ。温めますか？", aiEn: "Welcome. Shall I heat it up?", you: "はい、お願いします。" },
  de: { scene: "Bäckerei · Leipzig", persona: "Frau Weber", ai: "Guten Morgen! Bitte schön, was darf es sein?", aiEn: "Good morning! What can I get you?", you: "Ich nehme zwei Brötchen, bitte." },
  en: { scene: "Coffee shop · anywhere", persona: "Maya", ai: "Hi there! What can I get you?", aiEn: "", you: "Can I have a medium latte, please?" },
};

export default function Landing() {
  const router = useRouter();
  const { onboarded, lang: chosen, hydrated } = usePrefs();
  const [lang, setLang] = useState<Lang>("ko");
  const [paused, setPaused] = useState(false);

  // The page re-tints with each language: the accent system, demonstrated.
  useEffect(() => {
    applyLang(lang);
  }, [lang]);
  useEffect(() => () => applyLang(usePrefs.getState().lang), []);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || paused) return;
    const timer = setInterval(() => {
      setLang((current) => LANG_ORDER[(LANG_ORDER.indexOf(current) + 1) % LANG_ORDER.length]!);
    }, 3600);
    return () => clearInterval(timer);
  }, [paused]);

  const sample = SAMPLES[lang];
  const start = () => router.push(hydrated && onboarded ? "/home" : "/onboarding");

  return (
    <div className="glow-accent relative min-h-dvh overflow-hidden transition-colors duration-700">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 pt-6">
        <span className="font-display text-2xl tracking-tight">TalkScene</span>
        <Link href={chosen && onboarded ? "/home" : "/settings#account"} className="tap inline-flex items-center rounded-full px-4 text-sm font-medium text-ink-2 hover:text-ink">
          {onboarded ? "Open app" : "Sign in"}
        </Link>
      </header>

      <main className="mx-auto grid max-w-5xl gap-12 px-6 pb-16 pt-10 md:grid-cols-[1.1fr_1fr] md:items-center md:pt-20">
        <section>
          <p className="reveal text-[12px] font-semibold uppercase tracking-[0.18em] text-accent-ink" style={{ ["--i" as string]: 0 }}>
            Korean · Japanese · German · English
          </p>
          <h1 className="reveal mt-4 font-display text-[44px] leading-[1.02] tracking-[-0.025em] text-ink md:text-[68px]" style={{ ["--i" as string]: 1 }}>
            Speak first.
            <br />
            <em className="text-accent-ink">Study second.</em>
          </h1>
          <p className="reveal mt-5 max-w-md text-[17px] leading-relaxed text-ink-2 pretty" style={{ ["--i" as string]: 2 }}>
            Pick a real situation — a hotel desk, a pharmacy, a job interview — and talk it through with a character
            for ten turns. Then get honest feedback on what you said and how it sounded.
          </p>
          <div className="reveal mt-8 flex flex-wrap items-center gap-3" style={{ ["--i" as string]: 3 }}>
            <Button size="lg" iconRight="arrow" onClick={start}>
              Start a conversation
            </Button>
            <span className="text-[13px] text-ink-3">No account needed · works in your browser</span>
          </div>

          <ul className="reveal mt-12 grid max-w-md grid-cols-3 gap-4 text-[13px] text-ink-2" style={{ ["--i" as string]: 4 }}>
            <li>
              <span className="block text-[22px] font-semibold text-ink">32</span>
              scenes, A1 to B2
            </li>
            <li>
              <span className="block text-[22px] font-semibold text-ink">10–15</span>
              turns each
            </li>
            <li>
              <span className="block text-[22px] font-semibold text-ink">1</span>
              report that tells the truth
            </li>
          </ul>
        </section>

        <section aria-label="Example conversation" className="relative" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
          <div className="card relative p-5 md:p-6">
            <div className="flex items-center justify-between">
              <p className="text-[12px] font-medium text-ink-3">{sample.scene}</p>
              <div className="flex gap-1" role="tablist" aria-label="Choose a language">
                {LANG_ORDER.map((code) => (
                  <button
                    key={code}
                    role="tab"
                    aria-selected={code === lang}
                    aria-label={LANGS[code].name}
                    onClick={() => {
                      setPaused(true);
                      setLang(code);
                    }}
                    className={cx("tap grid place-items-center rounded-full transition", code === lang ? "opacity-100" : "opacity-45 hover:opacity-100")}
                  >
                    <LangMark lang={code} size="sm" />
                  </button>
                ))}
              </div>
            </div>

            <div key={lang} className="mt-5 space-y-4" aria-live="polite">
              <div className="bubble-in flex gap-3">
                <div className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft font-display text-accent-ink">{sample.persona.slice(0, 1)}</div>
                <div className="rounded-[22px] rounded-tl-md bg-paper-2 px-4 py-3">
                  <p lang={lang} className="target text-[19px] text-ink">{sample.ai}</p>
                  {sample.aiEn ? <p className="mt-1.5 text-[13px] text-ink-3">{sample.aiEn}</p> : null}
                </div>
              </div>
              <div className="bubble-in flex justify-end" style={{ animationDelay: "380ms" }}>
                <div className="rounded-[22px] rounded-br-md bg-ink px-4 py-3 text-paper">
                  <p lang={lang} className="target text-[17px]">{sample.you}</p>
                </div>
              </div>
            </div>

            <div className="mt-6 flex items-center justify-center gap-4 border-t border-line pt-5">
              <span className="grid size-14 place-items-center rounded-full bg-accent text-on-accent shadow-[0_14px_30px_-12px_rgb(var(--glow)/0.9)]">
                <Icon name="mic" size={26} />
              </span>
              <div className="text-[13px] leading-snug text-ink-2">
                <p className="font-medium text-ink">Hold to speak</p>
                <p>or type — your call, every turn</p>
              </div>
            </div>
          </div>

          <div className="card absolute -bottom-6 -left-4 hidden w-56 rotate-[-3deg] p-4 md:block">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">After the chat</p>
            <p className="mt-2 text-[34px] font-semibold leading-none text-ink">78</p>
            <p className="mt-1 text-[12px] text-ink-2">≈ A2+ · 3 of 4 goals</p>
            <div className="mt-3 h-1.5 rounded-full bg-accent-soft">
              <div className="h-full w-[78%] rounded-full bg-accent" />
            </div>
          </div>
        </section>
      </main>

      <footer className="mx-auto max-w-5xl px-6 pb-10 text-[12px] text-ink-3">
        Your voice is processed to transcribe and assess it. Recordings are kept only if you opt in, and deleted after 30 days.
      </footer>
    </div>
  );
}
