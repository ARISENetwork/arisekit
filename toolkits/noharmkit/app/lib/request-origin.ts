import type { NextRequest } from "next/server";

export function requestOrigin(request: NextRequest): string {
  const site = new URL(request.url);
  const host = request.headers.get("host");
  if (host) site.host = host;
  return site.origin;
}
