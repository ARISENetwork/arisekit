export interface TextV2Applicability { state: "applicable" | "notApplicable" | "uncertain"; basis: string }

// Plain module: server components call this, so it must not live in a "use client" file.
export function applicabilityText({ state, basis }: TextV2Applicability): string {
  const source = basis === "case" ? "the case" : basis === "response" ? "the response" : null;
  if (state === "uncertain") return "Unclear whether this applies";
  if (state === "notApplicable") return source ? `Does not apply, based on ${source}` : "Does not apply";
  if (basis === "always") return "Applies to every case";
  return source ? `Applies, based on ${source}` : "Applies";
}
