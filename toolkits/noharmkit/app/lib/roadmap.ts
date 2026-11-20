import { STEP_NAMES } from "@/components/mc/nav";
import type { NavData } from "@/components/mc/nav";
import { stepHref } from "@/lib/caseset/routes";
import { STEP_KEYS, stepForRoute } from "@/lib/caseset/steps";
import type { DotState, StepKey } from "@/lib/caseset/steps";
import { noharmHref } from "@/lib/noharm-path";

export interface RoadmapStop { key: "welcome" | StepKey; name: string; href: string; dot: DotState; current: boolean }

export function roadmapStops(nav: NavData, local: string, params: Record<string, string | null>): RoadmapStop[] {
  const step = local === "/review" ? "rubrics" : stepForRoute(local.slice(1));
  return [
    { key: "welcome", name: "Welcome", href: noharmHref("/welcome"), dot: nav.benchmark ? "reviewed" : "none", current: local === "/welcome" },
    ...STEP_KEYS.map((key) => ({ key, name: STEP_NAMES[key], href: stepHref(key, params), dot: nav.dots[key], current: step === key })),
  ];
}
