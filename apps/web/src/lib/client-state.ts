"use client";

/**
 * Browser-only state, read without hydration mismatches.
 *
 * Pages are prerendered on the server, where there is no token in storage, no
 * microphone and no local clock. Reading those during render makes the server
 * HTML disagree with the client's first render (React error #418).
 * `useSyncExternalStore` with a server snapshot is the sanctioned fix: both
 * sides render the server snapshot during hydration, then React re-renders
 * with the real value.
 */

import { useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

/** False on the server and during hydration, true afterwards. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

export { SESSION_EVENT, useSessionInfo } from "./api";
