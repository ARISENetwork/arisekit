import { chooseBenchmark } from "@/lib/caseset/metrics";
import { stepForRoute } from "@/lib/caseset/steps";
import { localPath, noharmHref } from "@/lib/noharm-path";

export const BENCHMARK_COOKIE = "noharm-benchmark";

export function resolveBenchmarkSelection(
  names: string[],
  updatedAt: Record<string, string | null>,
  saved: string | undefined,
  configured: string | undefined,
): string | null {
  return chooseBenchmark(names, updatedAt, saved && names.includes(saved) ? saved : configured);
}

const RETURN_DEFAULT = noharmHref("/welcome");
const SHELL_PAGES = ["/welcome", "/dashboard", "/framework", "/guide", "/api-setup", "/projects"];

export function safeBenchmarkReturnPath(pathname: unknown): string {
  if (typeof pathname !== "string") return RETURN_DEFAULT;
  const local = localPath(pathname);
  if (local === null) return RETURN_DEFAULT;
  if (local === "/review") return noharmHref("/rubrics");
  if (SHELL_PAGES.includes(local)) return pathname;
  return stepForRoute(local.slice(1)) ? pathname : RETURN_DEFAULT;
}
