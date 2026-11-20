"use client";

import { useRef, useState } from "react";
import styles from "./KitsPage.module.css";

import type { Kit } from "@/lib/kits";
import localPrompts from "../../../../../docs/kits-data.json";

type Workflow = { prompt: string; capability: string };
const workflows: Readonly<Record<string, Workflow | undefined>> = localPrompts;

export function KitName({ name }: { name: string }): React.ReactElement {
  if (!name.endsWith("Kit")) return <span className={styles.kitPrefix}>{name}</span>;
  return <><span className={styles.kitPrefix}>{name.slice(0, -3)}</span><span className={styles.kitSuffix}>Kit</span></>;
}

function setClip(row: HTMLElement, playing: boolean): void {
  const clip = row.querySelector("video");
  if (!clip || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (playing) void clip.play().catch(() => {});
  else clip.pause();
}

export function KitRow({ kit }: { kit: Kit }): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("");
  const promptField = useRef<HTMLTextAreaElement>(null);
  const panelId = "workflow-" + kit.id;

  const workflow = workflows[kit.id];
  if (!kit.comingSoon && !workflow) throw new Error("Missing authoring prompt for " + kit.name);

  async function copyPrompt(prompt: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(prompt);
      setStatus("Copied.");
    } catch {
      promptField.current?.focus();
      promptField.current?.select();
      setStatus("Prompt selected. Use your device’s Copy command.");
    }
  }

  return (
    <li className={styles.row} data-soon={kit.comingSoon ? "" : undefined}
      onMouseEnter={event => setClip(event.currentTarget, true)} onMouseLeave={event => setClip(event.currentTarget, false)}
      onFocus={event => setClip(event.currentTarget, true)} onBlur={event => setClip(event.currentTarget, false)}>
      {kit.clip
        ? <video className={styles.media} src={kit.clip} poster={kit.image} muted loop playsInline preload="metadata" aria-hidden="true" />
        : <img className={styles.media} src={kit.image} alt="" />}
      <span className={styles.name}><KitName name={kit.name} /></span>
      <span className={styles.description}>
        {kit.description}
        {kit.link && <> <a className={styles.sourceLink} href={kit.link.href} target="_blank" rel="noopener noreferrer">{kit.link.label} ↗</a></>}
      </span>
      <span className={styles.tags}>{kit.formats.map(format => <span key={format} className={styles.tag}>{format}</span>)}</span>
      <span className={styles.action}>
        {kit.comingSoon ? <span className={styles.status}>Coming soon</span> : (
          <button className={styles.open} type="button" aria-expanded={open} aria-controls={panelId}
          aria-label={(open ? "Close " : "Open ") + kit.name} onClick={() => { setOpen(!open); setStatus(""); }}>
            {open ? "Close" : "Open"}
          </button>
        )}
      </span>
      {workflow && (
        <div id={panelId} hidden={!open} className={styles.promptPanel}>
          <p>{workflow.capability}</p>
          <p><label htmlFor={panelId + "-prompt"}>Open the ARISEKit repository in your coding agent and paste this prompt.</label></p>
          <textarea id={panelId + "-prompt"} ref={promptField} className={styles.promptText} readOnly value={workflow.prompt} />
          <button type="button" className={styles.copy} onClick={() => void copyPrompt(workflow.prompt)}>Copy prompt</button>
          <span role="status" className={styles.copyStatus}>{status}</span>
        </div>
      )}
    </li>
  );
}
