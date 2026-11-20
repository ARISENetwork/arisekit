"use client";

import { useEffect, useState } from "react";

import { isValidReviewerId } from "@/lib/clinician-review";

export const REVIEWER_STORAGE_KEY = "noharm:reviewer-id:v1";
export const LOCAL_REVIEWER_ID = "local";

export function useReviewerId(): { hydrated: boolean; reviewerId: string | null } {
  const [reviewerId, setState] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let id = LOCAL_REVIEWER_ID;
    try {
      const stored = window.localStorage.getItem(REVIEWER_STORAGE_KEY);
      // Reuse an existing save namespace so earlier local drafts remain accessible.
      if (stored && isValidReviewerId(stored)) id = stored;
    } catch {
      // Local review also works when browser storage is unavailable.
    }
    setState(id);
    setHydrated(true);
  }, []);

  return { hydrated, reviewerId };
}
