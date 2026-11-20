"use client";

import { createContext, useContext, useEffect, useId, useRef, useState, type FormEvent, type ReactElement, type ReactNode } from "react";
import { ApiStageAction } from "./ApiExecution";
import { brokenPromptsNote, responsesAsk, type ChosenPrompt, type OutdatedResponses } from "@/lib/response-prompt-picker";

interface PromptChoice { prompt: ChosenPrompt | null; choose: (prompt: ChosenPrompt | null) => void }
const Context = createContext<PromptChoice | null>(null);

export function ResponsePromptProvider({ children }: { children: ReactNode }): ReactElement {
  const [prompt, choose] = useState<ChosenPrompt | null>(null);
  return <Context value={{ prompt, choose }}>{children}</Context>;
}

export const useChosenPrompt = (): ChosenPrompt | null => useContext(Context)?.prompt ?? null;

export function CollectResponses({ project, base, outdated }: { project: string; base: string; outdated?: OutdatedResponses }): ReactElement {
  const ask = responsesAsk(base, useChosenPrompt(), outdated);
  return <ApiStageAction project={project} action={ask.action} label={ask.label} prompt={ask.prompt} apiLead={ask.apiLead} />;
}

const NEW = "__new__";
const FIELD = "rounded-md border border-mc-line-strong bg-mc-surface px-2.5 py-1.5 text-sm text-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent";
const BUTTON = "rounded-md border border-mc-line-strong bg-mc-surface px-3 py-1.5 text-sm font-medium text-mc-ink transition-colors hover:border-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent disabled:opacity-50 motion-reduce:transition-none";

async function failure(response: Response): Promise<string> {
  const text = await response.text();
  try { return (JSON.parse(text) as { error?: string }).error ?? text; }
  catch { return text || `Saving the prompt returned HTTP ${response.status}.`; }
}

export default function ResponsePromptPicker({ project, unavailable, inUse }: { project: string; unavailable?: string; inUse?: boolean }): ReactElement | null {
  const choice = useContext(Context);
  const id = useId();
  const [prompts, setPrompts] = useState<(ChosenPrompt & { sha256?: string })[]>([]);
  const [used, setUsed] = useState<string[]>([]);
  const [mode, setMode] = useState<"new" | "edit" | null>(null);
  const [replaces, setReplaces] = useState<string | undefined>(undefined);
  const selectRef = useRef<HTMLSelectElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const open = mode !== null;
  useEffect(() => { if (mode) nameRef.current?.focus(); }, [mode]);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/prompts?project=${encodeURIComponent(project)}`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(await failure(response));
        const data = await response.json() as { prompts: ChosenPrompt[]; used: string[] };
        setPrompts(data.prompts); setUsed(data.used);
      })
      .catch((caught: Error) => { if (!controller.signal.aborted) setLoadError(caught.message); });
    return () => controller.abort();
  }, [project]);
  if (!choice) return null;
  const broken = unavailable ?? loadError;
  const current = choice.prompt ? prompts.find(prompt => prompt.id === choice.prompt!.id) ?? choice.prompt : null;
  const locked = Boolean(current && used.includes(current.id));
  const openForm = (next: "new" | "edit", initialName: string, initialText: string, replacing?: string): void => { setName(initialName); setText(initialText); setReplaces(replacing); setError(null); setMode(next); };
  const close = (): void => { setMode(null); setError(null); selectRef.current?.focus(); };
  const select = (value: string): void => {
    if (value === NEW) { openForm("new", "", ""); return; }
    setMode(null); setError(null);
    choice.choose(prompts.find(prompt => prompt.id === value) ?? null);
  };
  const save = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setSaving(true); setError(null);
    try {
      const response = await fetch("/api/prompts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, name, text, ...(replaces ? { replaces } : {}) }) });
      if (!response.ok) throw new Error(await failure(response));
      const { prompt } = await response.json() as { prompt: ChosenPrompt };
      setPrompts(previous => replaces ? previous.map(item => item.id === replaces ? prompt : item) : [...previous, prompt]);
      choice.choose(prompt);
      close();
    } catch (caught) { setError((caught as Error).message); }
    finally { setSaving(false); }
  };
  const remove = async (prompt: ChosenPrompt): Promise<void> => {
    setSaving(true); setError(null);
    try {
      const response = await fetch(`/api/prompts?project=${encodeURIComponent(project)}&id=${encodeURIComponent(prompt.id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await failure(response));
      setPrompts(previous => previous.filter(item => item.id !== prompt.id));
      choice.choose(null);
      close();
    } catch (caught) { setError((caught as Error).message); }
    finally { setSaving(false); }
  };
  return <div className="flex flex-col gap-2">
    <div className="flex flex-wrap items-center gap-2.5">
      <label className="text-sm font-medium" htmlFor={`${id}-select`}>Prompt</label>
      <select className={FIELD} id={`${id}-select`} ref={selectRef} disabled={Boolean(broken)} value={mode === "new" ? NEW : current?.id ?? ""} onChange={event => select(event.target.value)}>
        <option value="">No prompt</option>
        {prompts.map(prompt => <option key={prompt.id} value={prompt.id}>{prompt.name}</option>)}
        <option value={NEW}>New prompt...</option>
      </select>
      {locked && <span className="rounded-md border border-mc-line px-2 py-0.5 text-xs text-mc-muted">Locked</span>}
      {locked && current && <button className={BUTTON} type="button" onClick={() => openForm("new", "", current.text)}>Save as new prompt</button>}
      {current && !locked && <button className={BUTTON} disabled={saving} type="button" onClick={() => openForm("edit", current.name, current.text, current.id)}>Edit</button>}
      {current && !locked && <button className={BUTTON} disabled={saving} type="button" onClick={() => { void remove(current); }}>Delete</button>}
    </div>
    {current && !open && <p className="m-0 whitespace-pre-wrap break-words rounded-md border border-mc-line bg-mc-surface-2 p-2.5 text-xs text-mc-muted">{current.text}</p>}
    <div className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
      <form className="flex min-h-0 flex-col gap-2 overflow-hidden" inert={!open} onSubmit={event => { void save(event); }}>
        <label className="flex flex-col gap-1 p-0.5 text-sm font-medium">Name<input className={FIELD} ref={nameRef} maxLength={64} required value={name} onChange={event => setName(event.target.value)} /></label>
        <label className="flex flex-col gap-1 p-0.5 text-sm font-medium">Text<textarea className={`${FIELD} min-h-28`} required value={text} onChange={event => setText(event.target.value)} /></label>
        <div className="flex gap-2 p-0.5">
          <button className={BUTTON} disabled={saving} type="submit">{saving ? "Saving..." : "Save"}</button>
          <button className={BUTTON} type="button" onClick={close}>Cancel</button>
        </div>
      </form>
    </div>
    {broken && <p className="m-0 text-xs text-mc-bad" role="alert">Saved prompts cannot be used until this is fixed: {broken} {brokenPromptsNote(inUse)}</p>}
    {error && <p className="m-0 text-xs text-mc-bad" role="alert">{error}</p>}
  </div>;
}
