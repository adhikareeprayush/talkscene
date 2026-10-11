import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[70dvh] max-w-md flex-col items-center justify-center px-6 text-center">
      <p lang="ja" className="target text-5xl text-ink-3">
        迷子？
      </p>
      <h1 className="mt-4 font-display text-3xl text-ink">This page wandered off</h1>
      <p className="mt-2 text-ink-2">The scene you were looking for is not here.</p>
      <Link href="/home" className="tap mt-6 inline-flex h-12 items-center rounded-full bg-accent px-5 font-medium text-on-accent">
        Back to home
      </Link>
    </div>
  );
}
