"use client";

import type { ReactElement } from "react";
import type { ProjectExecutionMode } from "@/lib/project-mode";
import ApiReadinessNotice from "./ApiReadiness";
import styles from "./ProjectModeField.module.css";

export default function ProjectModeField({ id, value, onChange, disabled = false }: { id: string; value: ProjectExecutionMode; onChange: (mode: ProjectExecutionMode) => void; disabled?: boolean }): ReactElement {
  return <fieldset className={styles.field} disabled={disabled}>
    <legend>Mode</legend>
    <div className={styles.options}>
      <label className={styles.option}>
        <input type="radio" name="execution_mode" id={`${id}-api`} value="api" checked={value === "api"} onChange={() => onChange("api")} />
        <span><strong>API Mode</strong><small>Use OpenRouter API credits to drive the pipeline</small></span>
      </label>
      <label className={styles.option}>
        <input type="radio" name="execution_mode" id={`${id}-local`} value="local" checked={value === "local"} onChange={() => onChange("local")} />
        <span><strong>Local Mode</strong><small>Use your local coding agent (Claude Code, Codex, etc) to drive the pipeline</small></span>
      </label>
    </div>
    {value === "api" && <ApiReadinessNotice compact />}
  </fieldset>;
}
