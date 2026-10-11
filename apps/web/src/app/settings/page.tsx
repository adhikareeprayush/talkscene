"use client";

import Link from "next/link";
import { useSessionInfo } from "@/lib/client-state";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Page } from "@/components/AppShell";
import { QuotaMeter } from "@/components/catalog";
import { ErrorBanner } from "@/components/feedback";
import { Icon } from "@/components/Icon";
import { Button, Display } from "@/components/ui";
import { API_URL, api, client, problemMessage, useMe, useUpdateMe, useUsage } from "@/lib/api";
import { recognitionSupported, speak } from "@/lib/audio/speech";
import { cx } from "@/lib/format";
import { LANGS } from "@/lib/lang";
import { usePrefs } from "@/lib/store/prefs";

export default function Settings() {
  const me = useMe();
  const usage = useUsage();
  const update = useUpdateMe();
  const prefs = usePrefs();
  const p = me.data?.prefs;
  const session = useSessionInfo();
  const guest = me.data?.is_guest ?? session.guest;

  const patchPrefs = (body: Record<string, unknown>) => update.mutate({ prefs: body } as never);

  return (
    <Page>
      <Display className="reveal text-[38px]">Settings</Display>
      {update.error ? <ErrorBanner className="mt-4" message={problemMessage(update.error)} /> : null}

      <Account guest={guest} email={me.data?.email ?? null} />

      <Group title="Voice" icon="speaker">
        <Segmented
          label="Character voice"
          value={p?.tts_provider ?? "standard"}
          options={[["standard", "Standard", "Your browser’s voice — unlimited"], ["premium", "Premium", "Neural voice — monthly allowance"]]}
          onChange={(v) => patchPrefs({ tts_provider: v })}
        />
        <Segmented
          label="Speed"
          value={String(p?.tts_rate ?? 1)}
          options={[["0.85", "Slower", ""], ["1", "Normal", ""], ["1.15", "Faster", ""]]}
          onChange={(v) => patchPrefs({ tts_rate: Number(v) })}
        />
        <Button variant="secondary" size="sm" icon="play" onClick={() => prefs.lang && void speak(LANGS[prefs.lang].hello, prefs.lang, p?.tts_rate ?? 1)}>
          Test voice
        </Button>
      </Group>

      <Group title="Display" icon="eye">
        <Switch label="Show romanization" description="Latin-letter readings under Korean and Japanese lines." checked={p?.show_romanization ?? true} onChange={(v) => patchPrefs({ show_romanization: v })} />
        <Switch label="Translations open by default" description="Otherwise tap Translate on any line." checked={p?.show_translation ?? false} onChange={(v) => patchPrefs({ show_translation: v })} />
        <Segmented
          label="Theme"
          value={prefs.theme}
          options={[["system", "System", ""], ["light", "Light", ""], ["dark", "Dark", ""]]}
          onChange={(v) => {
            prefs.set({ theme: v as "system" | "light" | "dark" });
            patchPrefs({ theme: v });
          }}
        />
      </Group>

      <Group title="Learning" icon="target">
        <Segmented
          label="Daily goal"
          value={String(me.data?.daily_goal_minutes ?? prefs.dailyGoal)}
          options={[["5", "5 min", ""], ["10", "10 min", ""], ["15", "15 min", ""], ["20", "20 min", ""]]}
          onChange={(v) => {
            prefs.set({ dailyGoal: Number(v) });
            update.mutate({ daily_goal_minutes: Number(v) } as never);
          }}
        />
        <Segmented
          label="Corrections"
          value={p?.correction_style ?? "end_only"}
          options={[["end_only", "At the end", "No interruptions mid-roleplay"], ["gentle_recast", "Gentle recasts", "The character rephrases naturally"]]}
          onChange={(v) => patchPrefs({ correction_style: v })}
        />
        <Link href="/onboarding" className="tap inline-flex items-center gap-1 text-[14px] font-medium text-accent-ink">
          Change language or level <Icon name="forward" size={15} />
        </Link>
      </Group>

      <Group title="Allowances" icon="chart">
        {usage.data ? (
          <div className="divide-y divide-line">
            {usage.data.meters.map((m) => (
              <QuotaMeter key={m.key} label={m.label} used={m.used} limit={m.limit} unit={m.unit} resets={m.resets} />
            ))}
          </div>
        ) : (
          <p className="text-[14px] text-ink-3">Loading…</p>
        )}
        {usage.data?.byok_active ? <p className="text-[13px] text-great">Using your own provider keys — service limits do not apply.</p> : null}
      </Group>

      <Privacy guest={guest} keepAudio={p?.keep_audio ?? false} onKeepAudio={(v) => patchPrefs({ keep_audio: v })} />

      {!guest ? <Byok configured={me.data?.byok_configured ?? []} /> : null}

      <p className="mt-10 pb-6 text-center text-[12px] text-ink-3">TalkScene · API {API_URL.replace(/^https?:\/\//, "")}</p>
    </Page>
  );
}

function Group({ title, icon, children }: { title: string; icon: "speaker" | "eye" | "target" | "chart" | "user" | "settings" | "alert"; children: ReactNode }) {
  return (
    <section className="card reveal mt-6 p-5">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><Icon name={icon} size={18} className="text-ink-3" /> {title}</h2>
      <div className="mt-4 space-y-5">{children}</div>
    </section>
  );
}

function Segmented({ label, value, options, onChange }: { label: string; value: string; options: [string, string, string][]; onChange: (v: string) => void }) {
  const active = options.find(([v]) => v === value);
  return (
    <fieldset>
      <legend className="text-[14px] font-medium text-ink">{label}</legend>
      <div className="mt-2 flex gap-1 rounded-full bg-paper-2 p-1">
        {options.map(([v, text]) => (
          <label key={v} className={cx("tap flex flex-1 cursor-pointer items-center justify-center rounded-full text-[13px] font-semibold transition", value === v ? "bg-card text-ink shadow-sm" : "text-ink-3 hover:text-ink-2")}>
            <input type="radio" className="sr-only" checked={value === v} onChange={() => onChange(v)} />
            {text}
          </label>
        ))}
      </div>
      {active?.[2] ? <p className="mt-1.5 text-[12px] text-ink-3">{active[2]}</p> : null}
    </fieldset>
  );
}

function Switch({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <span>
        <span className="block text-[14px] font-medium text-ink">{label}</span>
        {description ? <span className="block text-[12.5px] text-ink-3 pretty">{description}</span> : null}
      </span>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
        <span className="h-7 w-12 rounded-full bg-line-strong transition peer-checked:bg-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent" />
        <span className="absolute left-1 top-1 size-5 rounded-full bg-card shadow transition peer-checked:translate-x-5" />
      </span>
    </label>
  );
}

function Account({ guest, email }: { guest: boolean; email: string | null }) {
  const router = useRouter();
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [form, setForm] = useState({ email: "", password: "", name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") await client.signUp({ email: form.email, password: form.password, display_name: form.name || undefined });
      else await client.signIn(form.email, form.password);
      router.refresh();
      window.location.reload();
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!guest) {
    return (
      <section id="account" className="card reveal mt-6 flex items-center justify-between gap-4 p-5">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-3">Signed in</p>
          <p className="mt-0.5 text-[15px] text-ink">{email}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { client.signOut(); window.location.href = "/"; }}>Sign out</Button>
      </section>
    );
  }

  return (
    <section id="account" className="card reveal mt-6 p-5">
      <h2 className="text-[15px] font-semibold text-ink">{mode === "signup" ? "Save your progress" : "Welcome back"}</h2>
      <p className="mt-1 text-[13px] text-ink-2">
        {mode === "signup" ? "You’re a guest. An account keeps your history, flashcards and drills — and brings along the sessions you already did." : "Sign in to pick up where you left off."}
      </p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        {mode === "signup" ? (
          <input aria-label="Name (optional)" placeholder="Name (optional)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="tap w-full rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-ink-3" autoComplete="name" />
        ) : null}
        <input aria-label="Email" type="email" required placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="tap w-full rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-ink-3" autoComplete="email" />
        <input aria-label="Password" type="password" required minLength={mode === "signup" ? 10 : 1} placeholder={mode === "signup" ? "Password (10+ characters)" : "Password"} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="tap w-full rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-ink-3" autoComplete={mode === "signup" ? "new-password" : "current-password"} />
        {error ? <ErrorBanner message={error} /> : null}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "One moment…" : mode === "signup" ? "Create account" : "Sign in"}</Button>
      </form>
      <button onClick={() => setMode(mode === "signup" ? "signin" : "signup")} className="tap mt-2 w-full text-center text-[13px] font-medium text-accent-ink">
        {mode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"}
      </button>
    </section>
  );
}

function Privacy({ guest, keepAudio, onKeepAudio }: { guest: boolean; keepAudio: boolean; onKeepAudio: (v: boolean) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [captions, setCaptions] = useState(false);
  useEffect(() => setCaptions(recognitionSupported()), []);

  const exportData = async () => {
    const response = await client.authedFetch("/v1/me/export");
    if (!response.ok) return;
    const blob = new Blob([JSON.stringify(await response.json(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "talkscene-export.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const remove = async () => {
    await api.DELETE("/v1/me");
    client.signOut();
    setDeleted(true);
    setTimeout(() => (window.location.href = "/"), 1200);
  };

  return (
    <Group title="Privacy" icon="alert">
      <Switch label="Keep my recordings" description="Lets you replay your own turns. Deleted automatically after 30 days. Off by default." checked={keepAudio} onChange={onKeepAudio} />
      <div className="rounded-2xl bg-paper-2 p-4 text-[13px] leading-relaxed text-ink-2">
        <p className="font-medium text-ink">Where your voice goes</p>
        <ul className="mt-1.5 list-disc space-y-1 pl-4">
          {captions ? <li>Live captions use your browser’s speech recognition; Chrome sends that audio to Google.</li> : null}
          <li>Your recording is transcribed by a speech provider to understand what you said. It is never used to train models.</li>
          <li>Transcripts stay with your account until you delete it.</li>
        </ul>
      </div>
      {!guest ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" icon="download" onClick={() => void exportData()}>Export my data</Button>
          {!confirming ? (
            <Button variant="ghost" size="sm" icon="trash" onClick={() => setConfirming(true)}>Delete account</Button>
          ) : (
            <div className="flex w-full flex-wrap items-center gap-2 rounded-2xl bg-attention-soft p-3 text-[13px] text-attention">
              <span className="flex-1">This permanently deletes your account, history, flashcards and recordings.</span>
              <Button size="sm" variant="secondary" onClick={() => setConfirming(false)}>Keep it</Button>
              <button onClick={() => void remove()} className="tap rounded-full bg-attention px-4 text-sm font-semibold text-paper">{deleted ? "Deleted" : "Delete forever"}</button>
            </div>
          )}
        </div>
      ) : null}
    </Group>
  );
}

const BYOK = [
  ["groq", "Groq", "Free tier · conversation + Whisper transcription"],
  ["gemini", "Google Gemini", "Free tier · conversation"],
  ["xai", "xAI Grok", "Paid · conversation"],
  ["deepgram", "Deepgram", "Transcription and voices (no Korean voice)"],
  ["azure_speech_key", "Azure Speech key", "Premium voices + pronunciation scoring"],
  ["azure_speech_region", "Azure region", "e.g. eastus"],
] as const;

function Byok({ configured }: { configured: string[] }) {
  const update = useUpdateMe();
  const [values, setValues] = useState<Record<string, string>>({});
  const save = () => update.mutate({ byok: values } as never, { onSuccess: () => setValues({}) });
  return (
    <Group title="Your own provider keys" icon="settings">
      <p className="text-[13px] text-ink-2 pretty">
        Bring your own keys and TalkScene spends <em>your</em> quota — the service limits above stop applying. Keys are encrypted at rest and never shown again.
      </p>
      <div className="space-y-3">
        {BYOK.map(([key, label, hint]) => (
          <label key={key} className="block">
            <span className="flex items-center justify-between text-[13px]">
              <span className="font-medium text-ink">{label}</span>
              {configured.includes(key) ? <span className="inline-flex items-center gap-1 text-great"><Icon name="check" size={13} /> saved</span> : null}
            </span>
            <input
              type={key === "azure_speech_region" ? "text" : "password"}
              autoComplete="off"
              placeholder={configured.includes(key) ? "•••••••• (leave blank to keep)" : hint}
              value={values[key] ?? ""}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
              className="tap mt-1 w-full rounded-full bg-paper-2 px-4 font-mono text-[13px] text-ink outline-none placeholder:font-sans placeholder:text-ink-3"
            />
          </label>
        ))}
      </div>
      {update.error ? <ErrorBanner message={problemMessage(update.error)} /> : null}
      <Button size="sm" onClick={save} disabled={!Object.values(values).some(Boolean) || update.isPending}>{update.isPending ? "Saving…" : "Save keys"}</Button>
    </Group>
  );
}
