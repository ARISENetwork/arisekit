import { cache } from "react";
import { cookies } from "next/headers";

import { benchmarkUpdatedAt, listBenchmarks, loadBenchmark } from "@/lib/caseset/metrics";
import type { Benchmark } from "@/lib/caseset/metrics";
import { projectsRoot } from "@/lib/caseset/paths";
import { withJsonlReadCache } from "@/lib/caseset/read";
import { BENCHMARK_COOKIE, resolveBenchmarkSelection } from "@/lib/caseset/selection";
import { projectTitles } from "@/lib/project-manage";

// titles: display names set on the projects page, by project.
export interface Current { bench: Benchmark; others: number; names: string[]; titles?: Record<string, string> }

// The layout and the page share one load per request.
export const getCurrent = cache(async (): Promise<Current | null> => {
  const root = projectsRoot();
  const names = listBenchmarks(root);
  const updatedAt = Object.fromEntries(names.map((name) => [name, benchmarkUpdatedAt(root, name)]));
  const jar = await cookies();
  const saved = jar.get(BENCHMARK_COOKIE)?.value;
  const name = resolveBenchmarkSelection(names, updatedAt, saved, process.env.NOHARM_BENCHMARK);
  return name === null ? null : { bench: withJsonlReadCache(() => loadBenchmark(root, name)), others: names.length - 1, names, titles: projectTitles(root, names) };
});
