import Frame from "@/components/mc/Frame";
import GuideContent from "@/components/mc/GuideContent";
import McShell from "@/components/mc/McShell";
import type { NavData } from "@/components/mc/nav";
import { getCurrent } from "@/lib/caseset/current";
import { STEP_KEYS } from "@/lib/caseset/steps";

export const dynamic = "force-dynamic";

export default async function GuidePage(): Promise<React.ReactNode> {
  const current = await getCurrent();
  const benchmark = current?.bench.name.toLowerCase() === "demo" ? undefined : current?.bench.name;
  const guide = <GuideContent benchmark={benchmark} />;
  if (current) return <McShell current={current} showSyntheticNotice={false}>{guide}</McShell>;
  const nav: NavData = {
    benchmark: "", benchmarks: [], dev: false, updatedLabel: null,
    dots: Object.fromEntries(STEP_KEYS.map((key) => [key, "none"])) as NavData["dots"],
  };
  return <Frame nav={nav}>{guide}</Frame>;
}
