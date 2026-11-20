export function useRouter(): never {
  throw new Error("Portable review uses file storage, not the server editor wrapper.");
}

export { useRouter as usePathname, useRouter as useSearchParams };
