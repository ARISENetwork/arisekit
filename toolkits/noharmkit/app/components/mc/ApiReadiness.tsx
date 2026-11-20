"use client";

import { useCallback, useEffect, useState, type ReactElement } from "react";
import type { ApiExecutionReadiness } from "@/lib/api-execution-readiness";
import Link from "@/components/MotionLink";
import { noharmHref } from "@/lib/noharm-path";
import styles from "./ApiExecution.module.css";

export function useApiReadiness(enabled = true): { readiness: ApiExecutionReadiness | null; error: string | null; refresh: () => Promise<ApiExecutionReadiness | null> } {
  const [readiness, setReadiness] = useState<ApiExecutionReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async (): Promise<ApiExecutionReadiness | null> => {
    try {
      const response = await fetch("/api/pipeline/readiness", { cache: "no-store" });
      if (!response.ok) throw new Error(`Execution readiness returned HTTP ${response.status}.`);
      const result = await response.json() as ApiExecutionReadiness;
      setReadiness(result); setError(null);
      return result;
    } catch (caught) { setReadiness(null); setError((caught as Error).message); return null; }
  }, []);
  useEffect(() => { if (enabled) void refresh(); }, [enabled, refresh]);
  return { readiness, error, refresh };
}

export default function ApiReadinessNotice({ compact = false }: { compact?: boolean }): ReactElement {
  const { readiness, error, refresh } = useApiReadiness();
  const content = <><div className={styles.summary}>
    {!compact && <strong>Execution availability</strong>}
    <p role="status">{error ?? readiness?.modelCalls.reason ?? "Checking the server runtime and API configuration. No model calls are made."}</p>
    {!compact && readiness && readiness.scoring.reason !== readiness.modelCalls.reason && <p>{readiness.scoring.reason}</p>}
    {readiness && !readiness.modelCalls.available && <p><Link href={noharmHref("/guide")}>Open the local workflow guide</Link></p>}
  </div>{!compact && <button className={styles.button} type="button" onClick={() => void refresh()}>Check availability</button>}</>;
  return compact ? <div aria-label="API execution availability">{content}</div> : <aside className={styles.status} aria-label="API execution availability">{content}</aside>;
}
