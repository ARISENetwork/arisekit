export const TUTORIAL_CASE = "Case001";
export interface TutorialDataset { task: string; solution: string; alternative: string; errors: string }

export const TUTORIAL_STAGES = [
  { key: "dataset", title: "Dataset", target: "input", heading: "Provide your dataset", guidance: "Add a task, solution, and possible errors. Then continue to the rubric." },
  { key: "rubrics", title: "Rubrics", target: "rubric", heading: "Review the draft rubric", guidance: "Open the full rubric editor to review decisions, options, appropriateness, and harm. Close it when you’re ready, then click Next. These example ratings are provisional." },
  { key: "responses", title: "Responses", target: "responses", heading: "Compare model responses", guidance: "Compare prepared responses from Model A, Model B, and Model C. Use OpenRouter to test multiple models in a real project." },
  { key: "autograding", title: "Autograding", target: "mapping", heading: "Review the judgments", guidance: "Check evidence quotes and omissions against the rubric. Automated judgments need review." },
  { key: "scores", title: "Scores", target: "scores", heading: "Inspect the scores", guidance: "Review coverage and harm. These previews remain provisional until all required ratings are resolved." },
  { key: "leaderboard", title: "Leaderboard", target: "dashboard", heading: "View overall progress", guidance: "Open Dashboard to view overall progress across your project. Your walkthrough is complete." },
] as const;

export function tutorialHref(href: string): string | null {
  const url = new URL(href, "http://tutorial.local");
  const route = url.pathname.replace(/^\/noharm\//, "").replace(/^\//, "");
  if (![...TUTORIAL_STAGES.map((stage) => stage.key), "review"].includes(route)) return null;
  url.searchParams.set("step", route);
  return `/noharm/tutorial?${url.searchParams.toString()}`;
}
