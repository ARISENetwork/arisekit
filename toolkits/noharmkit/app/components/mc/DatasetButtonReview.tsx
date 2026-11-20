"use client";

import { useCallback, useEffect, useState, type ReactElement } from "react";
import FloatingReviewPanel from "./FloatingReviewPanel";

const TREATMENTS = [
  { id: "separated", label: "Proposed", description: "Use Example inside Task. Bulk Upload beside Add Case. Workflow actions stay at the top-right." },
  { id: "current", label: "Current", description: "Use Example stays in the toolbar. Bulk Upload is beside Add Case." },
] as const;
export type DatasetButtonLayout = typeof TREATMENTS[number]["id"];

export default function DatasetButtonReview({ onChange }: { onChange: (value: DatasetButtonLayout) => void }): ReactElement | null {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  const change = useCallback((value: string): void => onChange(value as DatasetButtonLayout), [onChange]);
  if (!mounted) return null;
  const requested = new URLSearchParams(window.location.search).get("buttons");
  const initialChoice = TREATMENTS.find(item => item.id === requested)?.id ?? "separated";
  return <FloatingReviewPanel title="Action placement" label="Dataset action review" batch="dataset-actions-2" choices={TREATMENTS} baseline="current" initialChoice={initialChoice} onChange={change} />;
}
