export function toolkitPrompt(prompt: string): string {
  return `Work in toolkits/noharmkit within the ARISEKit checkout. Read its AGENTS.md and use its canonical stage skills.\n\n${prompt}`;
}
