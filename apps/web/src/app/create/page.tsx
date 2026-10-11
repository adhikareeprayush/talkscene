"use client";

import type { Lang, Level, ScenarioBrief } from "@talkscene/sdk";
import Link from "next/link";
import { useSessionInfo } from "@/lib/client-state";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Page } from "@/components/AppShell";
import { GoalChecklist } from "@/components/Conversation";
import { ErrorBanner, LevelBadge } from "@/components/feedback";
import { LangMark } from "@/components/LangMark";
import { Icon } from "@/components/Icon";
import { Button, Chip, Display } from "@/components/ui";
import { api, ensureSession, problemMessage, useStartSession } from "@/lib/api";
import { LANG_ORDER, LANGS, LEVELS } from "@/lib/lang";
import { useLive } from "@/lib/store/session";
import { usePrefs } from "@/lib/store/prefs";

const IDEAS = [
  "Complaining politely about a noisy neighbour",
  "Returning a jacket that does not fit",
  "Asking a colleague to swap shifts",
  "Explaining a lost passport at the embassy",
];

export default function Create() {
  const router = useRouter();
  const prefs = usePrefs();
  const [prompt, setPrompt] = useState("");
  const [lang, setLang] = useState<Lang>(prefs.lang ?? "ko");
  const [level, setLevel] = useState<Level>(prefs.level);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);
  const start = useStartSession();
  const { guest } = useSessionInfo();

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      await ensureSession();
      const result = await api.POST("/v1/scenarios/custom", { body: { prompt, language: lang, level, publish: false } });
      if (result.data) setScenario(result.data.scenario);
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const begin = async () => {
    if (!scenario) return;
    const response = await start.mutateAsync({ scenario_id: scenario.id, target_turns: scenario.turn_limits.default, options: { input: "voice", tts_tier: "standard" } });
    useLive.getState().hydrate(response);
    router.push(`/session/${response.session_id}`);
  };

  return (
    <Page>
      <Display className="reveal text-[38px]">Create a scene</Display>
      <p className="reveal mt-1 text-ink-2" style={{ ["--i" as string]: 1 }}>Describe a situation you want to rehearse. We’ll write the character and the goals.</p>

      {!scenario ? (
        <section className="card reveal mt-6 space-y-5 p-5" style={{ ["--i" as string]: 2 }}>
          <label className="block">
            <span className="text-[14px] font-medium text-ink">The situation</span>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              maxLength={600}
              rows={3}
              placeholder="e.g. Asking my landlord to fix the heating before winter"
              className="mt-2 w-full resize-none rounded-[18px] bg-paper-2 px-4 py-3 text-[16px] text-ink outline-none placeholder:text-ink-3 focus-visible:shadow-[inset_0_0_0_2px_var(--accent)]"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {IDEAS.map((idea) => <Chip key={idea} onClick={() => setPrompt(idea)}>{idea}</Chip>)}
          </div>
          <div>
            <p className="text-[14px] font-medium text-ink">Language</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {LANG_ORDER.map((c) => <Chip key={c} selected={lang === c} onClick={() => setLang(c)}><LangMark lang={c} size="xs" /> {LANGS[c].name}</Chip>)}
            </div>
          </div>
          <div>
            <p className="text-[14px] font-medium text-ink">Level</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {LEVELS.map((l) => <Chip key={l.level} selected={level === l.level} onClick={() => setLevel(l.level)}>{l.level} · {l.label}</Chip>)}
            </div>
          </div>
          {error ? <ErrorBanner message={error} tone="improve" /> : null}
          <Button className="w-full" icon="wand" onClick={() => void generate()} disabled={busy || prompt.trim().length < 8}>
            {busy ? "Writing your scene…" : "Create scene"}
          </Button>
          <p className="text-[12px] text-ink-3">Scenes you create are private to you. Requests are screened for safety before anything is generated.</p>
        </section>
      ) : (
        <section className="card reveal mt-6 p-5" data-lang={scenario.language}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-accent-ink">Your scene</p>
              <h2 className="mt-1 font-display text-[28px] leading-tight text-ink">{scenario.title.en}</h2>
            </div>
            <LevelBadge level={scenario.level} />
          </div>
          <p className="mt-2 text-[15px] text-ink-2">{scenario.summary}</p>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <div><p className="text-[12px] font-medium text-ink-3">You are</p><p className="mt-0.5 text-[14.5px] text-ink">{scenario.user_role}</p></div>
            <div><p className="text-[12px] font-medium text-ink-3">You’ll talk to</p><p className="mt-0.5 text-[14.5px] text-ink">{scenario.persona.name}, {scenario.persona.role}</p></div>
          </div>
          <p className="mt-5 text-[12px] font-medium text-ink-3">Goals</p>
          <GoalChecklist className="mt-2" goals={scenario.goals.map((g) => ({ ...g, done: false, turn_completed: null }))} />
          {start.error ? <ErrorBanner className="mt-4" message={problemMessage(start.error)} /> : null}
          <div className="mt-5 flex flex-wrap gap-2">
            <Button iconRight="arrow" onClick={() => void begin()} disabled={start.isPending}>{start.isPending ? "Starting…" : "Start this scene"}</Button>
            <Button variant="secondary" icon="retry" onClick={() => setScenario(null)}>Try another</Button>
          </div>
        </section>
      )}
      {guest ? (
        <p className="mt-6 text-center text-[13px] text-ink-3"><Link href="/settings#account" className="font-medium text-accent-ink">Create an account</Link> to keep the scenes you write.</p>
      ) : null}
      <p className="mt-8 flex items-center justify-center gap-1.5 text-[12px] text-ink-3"><Icon name="info" size={14} /> Without an AI provider configured, generated scenes are placeholders.</p>
    </Page>
  );
}
