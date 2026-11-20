import ImportProject from "@/components/ImportProject";
import McShell from "@/components/mc/McShell";
import Welcome from "@/components/mc/Welcome";
import type { Benchmark } from "@/lib/caseset/metrics";
import { STEP_KEYS } from "@/lib/caseset/steps";

// The empty state: no benchmark folder yet.
export default function BenchmarkList({ root }: { root: string }) {
  const bench: Benchmark = {
    name: "", updatedAt: null, models: [], cases: [], attention: [], needAttention: 0,
    awaiting: { rubrics: 0, autograding: 0 }, meanF1: { value: null, n: 0, draft: false, provisional: false }, byModel: [],
    steps: Object.fromEntries(STEP_KEYS.map((key) => [key, {
      key, done: 0, total: 0, reviewed: key === "cases" || key === "responses" ? null : 0,
      reviewTotal: key === "cases" || key === "responses" ? null : 0, failed: 0, dot: "none",
    }])) as Benchmark["steps"],
  };
  return (
    <McShell current={{ bench, others: 0, names: [] }}>
      <Welcome bench={bench} projectsRoot={root} />
      <ImportProject />
    </McShell>
  );
}
