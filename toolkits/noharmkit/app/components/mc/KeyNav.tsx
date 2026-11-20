"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { useMotionNavigation } from "@/components/NavigationMotion";
import { keyTarget, navigationParams } from "@/lib/caseset/routes";
import { localPath } from "@/lib/noharm-path";

export default function KeyNav() {
  const navigate = useMotionNavigation();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      if ((e.target as Element | null)?.closest?.("input, select, textarea, [contenteditable='true']")) return;
      const target = keyTarget(e.key, localPath(pathname) ?? "/", navigationParams(searchParams));
      if (!target) return;
      e.preventDefault();
      navigate(target);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [searchParams, pathname, navigate]);
  return null;
}
