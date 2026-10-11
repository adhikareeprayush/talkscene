"use client";

import { useCallback, useRef } from "react";

/**
 * Enter-to-send that respects IME composition (plan §11.3 E).
 *
 * Korean and Japanese input methods use Enter to *confirm* a composition. A
 * naive `onKeyDown` handler would send "안녕하" half-typed. `isComposing` covers
 * modern browsers; keyCode 229 covers Safari, which reports composition Enter
 * that way and fires `compositionend` before `keydown`.
 */
export function useImeSubmit(onSubmit: () => void) {
  const composing = useRef(false);
  const justEnded = useRef(0);

  const onCompositionStart = useCallback(() => {
    composing.current = true;
  }, []);
  const onCompositionEnd = useCallback(() => {
    composing.current = false;
    justEnded.current = performance.now();
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      const native = event.nativeEvent as KeyboardEvent;
      const midComposition =
        composing.current || native.isComposing || native.keyCode === 229 || performance.now() - justEnded.current < 40;
      if (midComposition) return;
      event.preventDefault();
      onSubmit();
    },
    [onSubmit],
  );

  return { onKeyDown, onCompositionStart, onCompositionEnd };
}
