import type { SVGProps } from "react";

/**
 * One stroke icon set, drawn for this app at 24px / 1.75 stroke.
 * Decorative by default (`aria-hidden`); pass `title` when an icon is the only
 * label for a control.
 */
const PATHS = {
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" /></>,
  keyboard: <><rect x="2.5" y="6" width="19" height="12" rx="2.5" /><path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M7 14h10" /></>,
  bulb: <><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3Z" /></>,
  speaker: <><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></>,
  turtle: <><path d="M4 15c0-4 3.6-7 8-7s8 3 8 7H4Z" /><path d="M6 15l-1 3M18 15l1 3M20 13h1.5a1 1 0 0 0 0-2H20M9 8.5 12 15l3-6.5" /></>,
  translate: <><path d="M3.5 5.5h9M8 3.5v2M10.5 5.5c-.8 3.6-3.4 6.4-7 8M6 9c1.2 2 3 3.6 5 4.5" /><path d="m12.5 20.5 4-9 4 9M14 17h5" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  back: <path d="M15 5 8 12l7 7" />,
  forward: <path d="m9 5 7 7-7 7" />,
  more: <><circle cx="5.5" cy="12" r=".9" /><circle cx="12" cy="12" r=".9" /><circle cx="18.5" cy="12" r=".9" /></>,
  home: <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" />,
  grid: <><rect x="4" y="4" width="7" height="7" rx="2" /><rect x="13" y="4" width="7" height="7" rx="2" /><rect x="4" y="13" width="7" height="7" rx="2" /><rect x="13" y="13" width="7" height="7" rx="2" /></>,
  cards: <><rect x="3.5" y="7" width="13" height="13" rx="2.5" /><path d="M8 4h10.5A2 2 0 0 1 20.5 6v10.5" /></>,
  chart: <path d="M4 20h16M7 16v-5M12 16V6M17 16v-8" />,
  user: <><circle cx="12" cy="8.5" r="3.75" /><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" /></>,
  play: <path d="M8 5.5v13l10.5-6.5z" />,
  pause: <path d="M8 5.5v13M16 5.5v13" />,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" />,
  retry: <><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3L4.5 9" /><path d="M4.5 4.5V9H9" /></>,
  sparkle: <path d="M12 3.5c.6 4.3 2.2 5.9 6.5 6.5-4.3.6-5.9 2.2-6.5 6.5-.6-4.3-2.2-5.9-6.5-6.5 4.3-.6 5.9-2.2 6.5-6.5ZM18.5 15.5c.2 1.6.9 2.3 2.5 2.5-1.6.2-2.3.9-2.5 2.5-.2-1.6-.9-2.3-2.5-2.5 1.6-.2 2.3-.9 2.5-2.5Z" />,
  flame: <path d="M12 21c3.6 0 6.5-2.6 6.5-6.3 0-3.8-3-5.6-4-9.2-2.4 1.6-3.4 3.6-3.4 5.4-1-.4-1.8-1.4-2-2.6C7.4 9.8 5.5 12 5.5 14.7 5.5 18.4 8.4 21 12 21Z" />,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l1.9-1.4-2-3.4-2.2.9a7.6 7.6 0 0 0-2.6-1.5L14 2.8h-4l-.5 2.3a7.6 7.6 0 0 0-2.6 1.5l-2.2-.9-2 3.4 1.9 1.4a7.6 7.6 0 0 0 0 3l-1.9 1.4 2 3.4 2.2-.9a7.6 7.6 0 0 0 2.6 1.5l.5 2.3h4l.5-2.3a7.6 7.6 0 0 0 2.6-1.5l2.2.9 2-3.4z" /></>,
  bookmark: <path d="M7 4h10a1 1 0 0 1 1 1v15.5l-6-4-6 4V5a1 1 0 0 1 1-1Z" />,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.75h.01" /></>,
  alert: <><path d="M10.3 4.2 2.9 17.5A2 2 0 0 0 4.6 20.5h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" /><path d="M12 9.5v4M12 17h.01" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="2.75" /></>,
  wand: <><path d="m4 20 11-11M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 11l.6 1.4L21 13l-1.4.6L19 15l-.6-1.4L17 13l1.4-.6z" /></>,
  trash: <><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5" /></>,
  download: <><path d="M12 4v11M7 10.5l5 5 5-5M4.5 20h15" /></>,
  flag: <path d="M5.5 21V4.5M5.5 4.5h11l-2 4 2 4h-11" />,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r=".75" /></>,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 20,
  title,
  className,
  ...rest
}: { name: IconName; size?: number; title?: string } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      className={className}
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {PATHS[name]}
    </svg>
  );
}
