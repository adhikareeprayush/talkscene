"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/api";
import { usePrefs } from "@/lib/store/prefs";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const hydrate = usePrefs((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // PWA: cache the shell, the scenario list and past reports for offline review
  // (plan §2.2, §11.5). Development skips it so stale assets never confuse a
  // reload.
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is an enhancement; the app works without it */
    });
  }, []);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
