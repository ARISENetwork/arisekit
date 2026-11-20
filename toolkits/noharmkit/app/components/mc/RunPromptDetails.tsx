import type { ReactElement } from "react";
import type { RunPromptView } from "@/lib/response-prompt-picker";
import styles from "./ApiExecution.module.css";

export default function RunPromptDetails({ prompt }: { prompt: RunPromptView }): ReactElement {
  return <div className={styles.runPrompt}>
    <p>Prompt: {prompt.state === "ok" ? prompt.name : prompt.id}</p>
    {prompt.state === "ok" && <p className={styles.runPromptText}>{prompt.text}</p>}
    {prompt.state === "blocked" && <p className={styles.runPromptError} role="alert">{prompt.reason}</p>}
    {prompt.state === "loading" && <p>Checking the saved prompt.</p>}
  </div>;
}
