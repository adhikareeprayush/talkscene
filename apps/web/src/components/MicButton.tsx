"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { clock, cx } from "@/lib/format";
import type { MicState } from "@/lib/store/session";

import { Icon } from "./Icon";
import { Spinner } from "./ui";

const HOLD_MS = 350; // shorter than this is a tap: toggle mode
const CANCEL_PX = 90; // slide this far left to cancel (plan §11.3 E)

/**
 * The microphone (plan §11.3 E, "MicButton (state machine)").
 *
 * Three ways to drive it, because "hold to speak" alone excludes people:
 * * press and hold, release to send — push-to-talk;
 * * a quick tap starts, a second tap sends — for anyone who cannot hold;
 * * Space or Enter toggles, Escape cancels — keyboard and switch users.
 *
 * The level ring reads a ref inside its own animation frame and writes a CSS
 * variable, so a 60 fps meter never re-renders React.
 */
export function MicButton({
  state,
  levelRef,
  onStart,
  onStop,
  onCancel,
  onInterrupt,
  disabled,
  speakerName,
}: {
  state: MicState;
  levelRef: MutableRefObject<number>;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
  onInterrupt: () => void;
  disabled?: boolean;
  speakerName: string;
}) {
  const ring = useRef<HTMLSpanElement>(null);
  const pressedAt = useRef(0);
  const startX = useRef(0);
  const toggleMode = useRef(false);
  const [armedCancel, setArmedCancel] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // Level ring + elapsed timer while recording.
  useEffect(() => {
    if (state !== "recording") {
      ring.current?.style.setProperty("--level", "0");
      setElapsed(0);
      return;
    }
    let frame = 0;
    let smoothed = 0;
    const began = performance.now();
    let lastSecond = -1;
    const loop = () => {
      smoothed += (levelRef.current - smoothed) * 0.35;
      ring.current?.style.setProperty("--level", smoothed.toFixed(3));
      const second = Math.floor((performance.now() - began) / 1000);
      if (second !== lastSecond) {
        lastSecond = second;
        setElapsed(second);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [state, levelRef]);

  const press = (x: number) => {
    if (disabled) return;
    pressedAt.current = performance.now();
    startX.current = x;
    setArmedCancel(false);
    if (state === "idle") {
      toggleMode.current = false;
      onStart();
    } else if (state === "speaking") {
      // Barge-in: silence the character and let the learner talk.
      toggleMode.current = false;
      onInterrupt();
    } else if (state === "recording" && toggleMode.current) {
      toggleMode.current = false;
      onStop();
    }
  };

  const release = () => {
    if (state !== "recording") return;
    if (armedCancel) {
      setArmedCancel(false);
      toggleMode.current = false;
      onCancel();
      return;
    }
    const held = performance.now() - pressedAt.current;
    if (held < HOLD_MS && !toggleMode.current) {
      toggleMode.current = true; // quick tap: keep recording until the next tap
      return;
    }
    if (!toggleMode.current) onStop();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.repeat) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      if (state === "recording") onStop();
      else if (state === "speaking") onInterrupt();
      else if (state === "idle") {
        toggleMode.current = true;
        onStart();
      }
    } else if (event.key === "Escape" && state === "recording") {
      onCancel();
    }
  };

  const label = {
    idle: "Hold to speak",
    recording: armedCancel ? "Release to cancel" : toggleMode.current ? "Tap to send" : "Release to send",
    processing: "Listening back…",
    speaking: `${speakerName} is speaking — tap to interrupt`,
  }[state];

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative grid size-[112px] place-items-center">
        {/* Live level halo */}
        <span
          ref={ring}
          aria-hidden
          className={cx(
            "absolute inset-2 rounded-full bg-accent/25 transition-opacity duration-300",
            state === "recording" ? "opacity-100" : "opacity-0",
          )}
          style={{ transform: "scale(calc(1 + var(--level, 0) * 0.55))", transition: "transform 60ms linear" }}
        />
        {state === "recording" ? (
          <span aria-hidden className="absolute inset-3 rounded-full border-2 border-accent/60" style={{ animation: "ripple 1.6s ease-out infinite" }} />
        ) : null}
        {state === "speaking" ? (
          <span aria-hidden className="absolute inset-1 rounded-full bg-accent/15" style={{ animation: "breathe 1.8s ease-in-out infinite" }} />
        ) : null}

        <button
          type="button"
          disabled={disabled || state === "processing"}
          aria-label={state === "recording" ? "Stop recording and send" : state === "speaking" ? "Interrupt and speak" : "Start speaking"}
          aria-pressed={state === "recording"}
          onPointerDown={(e) => {
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            press(e.clientX);
          }}
          onPointerMove={(e) => {
            if (state !== "recording" || toggleMode.current) return;
            setArmedCancel(e.clientX - startX.current < -CANCEL_PX);
          }}
          onPointerUp={release}
          onPointerCancel={() => state === "recording" && !toggleMode.current && onCancel()}
          onKeyDown={onKeyDown}
          onContextMenu={(e) => e.preventDefault()}
          className={cx(
            "relative grid size-[84px] place-items-center rounded-full transition duration-200 touch-none",
            "shadow-[0_16px_36px_-14px_rgb(var(--glow)/0.85)] disabled:opacity-60",
            state === "recording"
              ? armedCancel
                ? "scale-90 bg-ink-3 text-paper"
                : "scale-105 bg-accent text-on-accent"
              : "bg-accent text-on-accent hover:scale-[1.03] active:scale-95",
          )}
        >
          {state === "processing" ? (
            <Spinner size={30} />
          ) : state === "recording" && armedCancel ? (
            <Icon name="x" size={32} />
          ) : state === "recording" ? (
            <Icon name="stop" size={30} />
          ) : (
            <Icon name="mic" size={32} />
          )}
        </button>
      </div>

      <div className="flex h-5 items-center gap-2 text-[13px] font-medium text-ink-2" aria-live="polite">
        {state === "recording" ? (
          <>
            <span className="size-2 animate-pulse rounded-full bg-attention" aria-hidden />
            <span className="tabular">{clock(elapsed)}</span>
            <span className="text-ink-3">·</span>
          </>
        ) : null}
        <span>{label}</span>
      </div>
      {state === "recording" && !toggleMode.current ? (
        <p className="-mt-2 text-[11px] text-ink-3" aria-hidden>
          ← slide to cancel
        </p>
      ) : null}
    </div>
  );
}

/** A compact bar meter for the onboarding mic test (plan §11.3 A, step 4). */
export function WaveformMeter({ levelRef, active, bars = 28 }: { levelRef: MutableRefObject<number>; active: boolean; bars?: number }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active) return;
    const history = new Array<number>(bars).fill(0);
    let frame = 0;
    const loop = () => {
      history.shift();
      history.push(levelRef.current);
      const nodes = container.current?.children;
      if (nodes) {
        for (let i = 0; i < nodes.length; i++) {
          const v = history[i] ?? 0;
          (nodes[i] as HTMLElement).style.transform = `scaleY(${Math.max(0.08, Math.min(1, v * 1.4))})`;
        }
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [active, bars, levelRef]);

  return (
    <div ref={container} className="flex h-16 items-center justify-center gap-[3px]" aria-hidden>
      {Array.from({ length: bars }, (_, i) => (
        <span
          key={i}
          className="h-full w-[4px] origin-center rounded-full bg-accent transition-transform duration-75"
          style={{ transform: "scaleY(0.08)", opacity: 0.35 + (i / bars) * 0.65 }}
        />
      ))}
    </div>
  );
}
