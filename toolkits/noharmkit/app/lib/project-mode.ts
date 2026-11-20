export type ProjectExecutionMode = "api" | "local";

export function projectMode(value: unknown): ProjectExecutionMode {
  if (value === undefined) return "api";
  if (value === "api" || value === "local") return value;
  throw new TypeError("Choose API Mode or Local Mode.");
}
