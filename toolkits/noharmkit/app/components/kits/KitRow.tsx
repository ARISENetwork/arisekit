"use client";

import { useRef, useState } from "react";
import styles from "./KitsPage.module.css";

type Kit = {
  id: string;
  name: string;
  task: string;
  capability: string;
  prompt: string;
  description?: string;
  formats: string[];
  image: string;
  clip?: string;
  link?: { label: string; href: string };
};

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

  async function copyPrompt(): Promise<void> {
    try {
      await navigator.clipboard.writeText(kit.prompt);
      setStatus("Copied.");
    } catch {
      promptField.current?.focus();
      promptField.current?.select();
      setStatus("Prompt selected. Use your device’s Copy command.");
    }
  }

  return (
    <li className={styles.row}
      onMouseEnter={event => setClip(event.currentTarget, true)} onMouseLeave={event => setClip(event.currentTarget, false)}
      onFocus={event => setClip(event.currentTarget, true)} onBlur={event => setClip(event.currentTarget, false)}>
      {kit.clip
        ? <video className={styles.media} src={kit.clip} poster={kit.image} muted loop playsInline preload="metadata" aria-hidden="true" />
        : <img className={styles.media} src={kit.image} alt="" />}
      <span className={styles.name}><KitName name={kit.name} /></span>
      <span className={styles.description}>
        {kit.description ?? kit.task}
        {kit.link && <> <a className={styles.sourceLink} href={kit.link.href} target="_blank" rel="noopener noreferrer">{kit.link.label} ↗</a></>}
      </span>
      <span className={styles.tags}>{kit.formats.map(format => <span key={format} className={styles.tag}>{format}</span>)}</span>
      <span className={styles.action}>
        <button className={styles.open} type="button" aria-expanded={open} aria-controls={panelId}
          aria-label={(open ? "Close " : "Open ") + kit.name} onClick={() => { setOpen(!open); setStatus(""); }}>
          {open ? "Close" : "Open"}
        </button>
      </span>
      <div id={panelId} hidden={!open} className={styles.promptPanel}>
        <p>{kit.capability}</p>
        <p><label htmlFor={panelId + "-prompt"}>Open the ARISEKit repository in your coding agent and paste this prompt.</label></p>
        <textarea id={panelId + "-prompt"} ref={promptField} className={styles.promptText} readOnly value={kit.prompt} />
        <button type="button" className={styles.copy} onClick={copyPrompt}>Copy prompt</button>
        <span role="status" className={styles.copyStatus}>{status}</span>
      </div>
    </li>
  );
}
