import type { StepParams } from "@/lib/caseset/routes";
import { localPath } from "@/lib/noharm-path";

export interface ResponseIdentity { model: string; trial: number }

const isResponsePage = (url: URL): boolean => localPath(url.pathname) === "/responses" || url.pathname === "/noharm/tutorial" && url.searchParams.get("step") === "responses";

export function isLocalResponseChange(previous: string | null, next: string): boolean {
  if (!previous) return false;
  const from = new URL(previous, "http://local");
  const to = new URL(next, "http://local");
  if (!isResponsePage(from) || !isResponsePage(to) || to.pathname !== from.pathname) return false;
  // The opening URL may omit the default case or item.
  return ["case", "item"].every((key) => !from.searchParams.get(key) || !to.searchParams.get(key) || from.searchParams.get(key) === to.searchParams.get(key));
}

export function localResponseIndex(views: ResponseIdentity[], initial: StepParams, query: Pick<URLSearchParams, "get"> | null): number {
  const fallback = views.findIndex((view) => view.model === initial.model && view.trial === initial.trial);
  if (!query || (query.get("case") && query.get("case") !== initial.caseId) || (query.get("item") && query.get("item") !== initial.itemId)) return fallback;
  const model = query.get("model") ?? initial.model;
  const trial = Number(query.get("trial") ?? initial.trial);
  const at = views.findIndex((view) => view.model === model && view.trial === trial);
  return at < 0 ? fallback : at;
}

// Only preloaded selections use native history; other destinations use normal navigation.
export function navigateLocalResponse(href: string, current: string, initial: StepParams, views: ResponseIdentity[], push: (href: string) => void): boolean {
  const from = new URL(current);
  const target = new URL(href, from);
  if (target.origin !== from.origin || !isResponsePage(from) || !isResponsePage(target) || from.pathname !== target.pathname) return false;
  if ((from.searchParams.get("case") && from.searchParams.get("case") !== initial.caseId) || (from.searchParams.get("item") && from.searchParams.get("item") !== initial.itemId)) return false;
  if (target.searchParams.get("case") !== initial.caseId || target.searchParams.get("item") !== initial.itemId) return false;
  const model = target.searchParams.get("model");
  const trial = Number(target.searchParams.get("trial"));
  if (!views.some((view) => view.model === model && view.trial === trial)) return false;
  if (target.href !== from.href) push(target.pathname + target.search + target.hash);
  return true;
}
