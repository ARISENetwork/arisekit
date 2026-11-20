"use client";

import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

const KEY = "theme";

// data-mode overrides the system setting; data-theme stays "berry" for the legacy screens.
export default function ThemeToggle({ iconOnly = false }: { iconOnly?: boolean }) {
  const [mode, setMode] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(KEY);
    } catch {
      // storage unavailable: follow the system setting
    }
    if (stored === "light" || stored === "dark") {
      document.documentElement.dataset.mode = stored;
      setMode(stored);
    } else {
      setMode(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    }
  }, []);
  const update = (): void => {
    const next = mode === "dark" ? "light" : "dark";
    document.documentElement.dataset.mode = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // storage unavailable: the choice lasts until reload
    }
    setMode(next);
  };
  const flip = (): void => {
    if (document.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const transition = document.startViewTransition(() => flushSync(update));
      void transition.ready.catch(() => {});
      void transition.finished.catch(() => {});
    } else update();
  };
  return (
    <button className="rounded-md border border-mc-line-strong bg-mc-surface px-2.5 py-1 text-[12.5px] text-mc-ink transition-colors hover:border-mc-ink" type="button" onClick={flip} aria-label={mode === "dark" ? "Light mode" : "Dark mode"} title={mode === "dark" ? "Light mode" : "Dark mode"}>
      {iconOnly ? <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{mode === "dark" ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></> : <path d="M20.8 13.3A9 9 0 0 1 10.7 3.2 9 9 0 1 0 20.8 13.3Z" />}</svg> : mode === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}
