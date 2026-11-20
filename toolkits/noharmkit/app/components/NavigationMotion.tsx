"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, Suspense, useCallback, useContext, useEffect, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";

import { navigationMotion } from "@/lib/navigation-motion";
import { isLocalResponseChange } from "@/lib/caseset/local-responses";
import { installDocumentNavigation, navigateDocument } from "../../../../apps/web/shared/documentNavigation";

type Navigate = (href: string, options?: { replace?: boolean; scroll?: boolean }) => void;
const NavigationContext = createContext<Navigate | null>(null);
const reducedMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const routeKey = (url: URL): string => {
  const query = url.searchParams.toString();
  return url.pathname + (query ? `?${query}` : "");
};

function RouteCommit({ onCommit }: { onCommit: (key: string) => void }) {
  const pathname = usePathname();
  const params = useSearchParams().toString();
  useLayoutEffect(() => { onCommit(pathname + (params ? `?${params}` : "")); }, [pathname, params, onCommit]);
  return null;
}

export const useOptionalMotionNavigation = (): Navigate | null => useContext(NavigationContext);

export function useMotionNavigation(): Navigate {
  const navigate = useOptionalMotionNavigation();
  if (!navigate) throw new Error("Motion navigation requires NavigationMotion");
  return navigate;
}

export default function NavigationMotion({ children }: { children: ReactNode }) {
  const router = useRouter();
  const motion = useRef<ReturnType<typeof navigationMotion> | null>(null);
  const previous = useRef<string | null>(null);
  const getMotion = useCallback(() => {
    if (!document.startViewTransition || reducedMotion()) return null;
    return motion.current ??= navigationMotion((update) => document.startViewTransition(update));
  }, []);
  const navigate = useCallback<Navigate>((href, options) => {
    const target = new URL(href, window.location.href);
    if (target.pathname === "/" || /^\/benchmark(?:\/|$)/.test(target.pathname)) {
      navigateDocument(href);
      return;
    }
    const update = (): void => {
      if (options?.replace) router.replace(href, { scroll: options.scroll });
      else router.push(href, { scroll: options?.scroll });
    };
    if (routeKey(target) === routeKey(new URL(window.location.href))) { update(); return; }
    const controller = getMotion();
    if (controller) controller.navigate(routeKey(target), update);
    else update();
  }, [getMotion, router]);
  useEffect(installDocumentNavigation, []);
  const commit = useCallback((key: string) => {
    const transitioned = motion.current?.commit(key);
    if (previous.current !== null && previous.current !== key && !transitioned && !isLocalResponseChange(previous.current, key) && !reducedMotion()) {
      // The fallback starts visible so route arrivals never flash an empty page.
      document.querySelector('main:not([data-workspace-transition="true"])')?.animate([{ opacity: 0.65 }, { opacity: 1 }], { duration: 260, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
    }
    previous.current = key;
  }, []);
  useEffect(() => {
    const onPop = (): void => {
      const key = routeKey(new URL(window.location.href));
      if (key !== previous.current && !isLocalResponseChange(previous.current, key)) getMotion()?.navigate(key, () => {});
    };
    window.addEventListener("popstate", onPop, true);
    return () => { window.removeEventListener("popstate", onPop, true); motion.current?.cancel(); };
  }, [getMotion]);
  return <NavigationContext value={navigate}>{children}<Suspense fallback={null}><RouteCommit onCommit={commit} /></Suspense></NavigationContext>;
}
