/**
 * Token storage and refresh.
 *
 * Access tokens are short-lived, so a single long session would otherwise start
 * 401-ing mid-conversation. `withFreshToken` refreshes at most once per expiry
 * and shares one in-flight refresh between concurrent callers — without that,
 * a screen firing four parallel queries would start four refreshes and three of
 * them would race.
 */

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  user_id: string;
  is_guest: boolean;
  expires_in: number;
};

export type StoredSession = TokenPair & { obtained_at: number };

const KEY = "talkscene.session";
/** Refresh this long before expiry, so a turn in flight never 401s. */
const SKEW_S = 120;

export interface TokenStore {
  read(): StoredSession | null;
  write(value: StoredSession | null): void;
}

/** Browser storage. Returns null anywhere `localStorage` is unavailable (SSR, private mode). */
export const browserTokenStore: TokenStore = {
  read() {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as StoredSession) : null;
    } catch {
      return null;
    }
  },
  write(value) {
    if (typeof window === "undefined") return;
    try {
      if (value === null) window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, JSON.stringify(value));
    } catch {
      /* private mode, blocked storage - the session simply does not persist */
    }
  },
};

export function createMemoryTokenStore(): TokenStore {
  let value: StoredSession | null = null;
  return {
    read: () => value,
    write: (next) => {
      value = next;
    },
  };
}

export function isExpired(session: StoredSession, now = Date.now()): boolean {
  return now >= session.obtained_at + (session.expires_in - SKEW_S) * 1000;
}

export function store(pair: TokenPair): StoredSession {
  return { ...pair, obtained_at: Date.now() };
}
