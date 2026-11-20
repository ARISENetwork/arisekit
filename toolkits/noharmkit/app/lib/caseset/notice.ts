// Pure and client-safe: the editor shows this after a save without reloading.
export function savedNotice(version: string): string {
  return `Saving replaces your reviewed copy (${version}).`;
}
