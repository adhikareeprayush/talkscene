import type { Metadata, Viewport } from "next";
import { Inter, Newsreader } from "next/font/google";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { PREFS_BOOT_SCRIPT } from "@/lib/store/prefs";

import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin", "latin-ext"], variable: "--font-inter", display: "swap" });
const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  display: "swap",
  style: ["normal", "italic"],
});
// Korean and Japanese use the platform's own CJK face (see globals.css):
// Android's system font is Noto Sans CJK, iOS/macOS ship Apple SD Gothic Neo
// and Hiragino, Windows ships Malgun Gothic and Yu Gothic. Bundling Noto KR/JP
// would add ~100 unicode-range files per face - megabytes on a phone - to
// render glyphs every target device already has.

export const metadata: Metadata = {
  title: { default: "TalkScene", template: "%s · TalkScene" },
  description: "Practise real conversations in Korean, Japanese, German and English — then get honest feedback.",
  applicationName: "TalkScene",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
  appleWebApp: { capable: true, title: "TalkScene", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f3ed" },
    { media: "(prefers-color-scheme: dark)", color: "#14120f" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${newsreader.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREFS_BOOT_SCRIPT }} />
      </head>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
        >
          Skip to content
        </a>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
