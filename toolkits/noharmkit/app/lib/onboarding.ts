export type WelcomeMode = "entry" | "new" | "resume";

export function isTutorialProject(name: string): boolean {
  return /^tutorial-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(name);
}

export function resumableProjects(names: string[], demo?: string): string[] {
  return names.filter((name) => name !== demo);
}

export function welcomeMode(names: string[], demo: string | undefined, requested: unknown): WelcomeMode {
  if (requested === "entry" || requested === "new" || requested === "resume") return requested;
  return "entry";
}
