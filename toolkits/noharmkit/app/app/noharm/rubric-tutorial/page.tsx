import type { ReactNode } from "react";

import RubricTutorial from "@/harmreview/components/RubricTutorial";

export const metadata = { title: "Rubric Editor Tutorial | ARISEKit" };

// noharm-science's rubric editor walkthrough, synced into app/harmreview. Nothing in it is saved.
export default function RubricTutorialPage(): ReactNode {
  return <main className="bg-[hsl(var(--background))] text-[hsl(var(--foreground))] [color-scheme:light]"><RubricTutorial /></main>;
}
