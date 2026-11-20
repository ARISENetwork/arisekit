"use client";

import { useEffect, useRef, type ReactNode } from "react";

// The host handles arrival motion without changing the shared reviewer workspace.
export default function ReviewArrival({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = root.current;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!host || reducedMotion.matches) return;
    let arrival: Animation | undefined;
    const observer = new MutationObserver((mutations) => {
      // The editor inserts its workspace after loading the selected rubric.
      // Animate that new region once, keeping its existing header stationary.
      if (!host.querySelector(":is([data-answer-table], [data-rubric]) h1")) return;
      const workspace = mutations.flatMap((mutation) => Array.from(mutation.addedNodes))
        .find((node): node is HTMLElement => node instanceof HTMLElement && node.querySelector("h1") !== null);
      if (!workspace) return;
      observer.disconnect();
      const easing = getComputedStyle(workspace).getPropertyValue("--motion-ease").trim() || "ease-out";
      arrival = workspace.animate([
        { opacity: 0, transform: "translateY(6px)" },
        { opacity: 1, transform: "translateY(0)" },
      ], { duration: 220, easing });
    });
    observer.observe(host, { childList: true, subtree: true });
    const stopMotion = () => {
      if (!reducedMotion.matches) return;
      observer.disconnect();
      arrival?.cancel();
    };
    reducedMotion.addEventListener("change", stopMotion);
    return () => {
      observer.disconnect();
      arrival?.cancel();
      reducedMotion.removeEventListener("change", stopMotion);
    };
  }, []);

  return <div ref={root}>{children}</div>;
}
