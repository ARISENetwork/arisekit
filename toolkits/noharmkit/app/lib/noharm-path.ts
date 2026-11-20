// Client-safe. Every NOHARMKit href and pathname check goes through here so the prefix lives in one place.
export const NOHARM_BASE = "/noharm";

export function noharmHref(local: string): string {
  return `${NOHARM_BASE}${local.startsWith("/") ? local : `/${local}`}`;
}

export function localPath(pathname: string): string | null {
  if (pathname === NOHARM_BASE) return "/";
  return pathname.startsWith(`${NOHARM_BASE}/`) ? pathname.slice(NOHARM_BASE.length) : null;
}
