"use client";

import { useSearchParams } from "next/navigation";
import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";

import { localResponseIndex, navigateLocalResponse, type ResponseIdentity } from "@/lib/caseset/local-responses";
import type { StepParams } from "@/lib/caseset/routes";

export interface ResponseView extends ResponseIdentity { output: ReactNode; picker: ReactNode; note: string }
export interface LocalResponsesData { initial: StepParams; views: ResponseView[] }
const Context = createContext<{ view: ResponseView | undefined; params: StepParams; navigate: (href: string) => boolean } | null>(null);

export default function LocalResponses({ initial, views, children }: LocalResponsesData & { children: ReactNode }) {
  const query = useSearchParams();
  const view = views[localResponseIndex(views, initial, query)];
  const params = view ? { ...initial, model: view.model, trial: view.trial } : initial;
  const navigate = (href: string): boolean => navigateLocalResponse(href, window.location.href, initial, views,
    (next) => window.history.pushState(null, "", next));
  return <Context value={{ view, params, navigate }}>{children}</Context>;
}

export const useLocalModelNavigation = () => useContext(Context)?.navigate;
export const useLocalResponseParams = () => useContext(Context)?.params;

export function LocalResponseSlot({ name, children }: { name: "output" | "picker" | "note"; children?: ReactNode }) {
  const view = useContext(Context)?.view;
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (name !== "output" || !root.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // Reveal the new response immediately; animate only this panel, without a route snapshot.
    const motion = root.current.animate([{ opacity: 0.65 }, { opacity: 1 }], { duration: 120, easing: "ease-out" });
    return () => motion.cancel();
  }, [name, view]);
  const content = view?.[name] ?? children;
  return name === "output" ? <div data-model-response className="flex flex-col gap-3.5" ref={root}>{content}</div> : <>{content}</>;
}
