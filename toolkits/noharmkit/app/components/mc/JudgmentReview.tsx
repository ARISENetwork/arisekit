"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import Link from "@/components/MotionLink";
import JudgmentReviewItem, { type ItemView } from "@/components/mc/JudgmentReviewItem";
import { carriedOver, JUDGMENT_CHANGED, needsEvidence, preselected, progress, verdictErrors, type ReviewItem, type Verdict } from "@/lib/caseset/judgment-review";
import {
  browserCopyKey, browserStore, choose as chooseSet, loadChoice, markSaved, readCopy, startAgain as moveAside, writeCopy,
  type BrowserCopy, type CopySide,
} from "@/lib/caseset/judgment-review-copy";
import {
  classifySave, DraftSaver, newDraftId, type Answers, type SaveProblem, type SaverState, type SendResult, type StoredDraft,
} from "@/lib/caseset/judgment-review-saving";
import { useReviewerId } from "@/lib/reviewer-id";
import listStyles from "./TextV2JudgmentList.module.css";
import styles from "./JudgmentReview.module.css";

const API = "/api/runs/judgment-review";

export interface ReviewSetup {
  project: string;
  model: string;
  id: string;
  trial: number;
  caseHref: string;
  rubricReviewed: boolean;
  criteria: Array<{ id: string; question: string; outsideRubric: boolean }>;
  // Response marks by quote text, so a quote here lights up its mark in the response.
  evidenceKeys: Record<string, string>;
}

export interface FinishedReviewResult { reviewedAt: string }

interface ReviewData {
  draft: (StoredDraft & { reviewer: string }) | null;
  // The stored draft names a judge record, response, case or rubric text that is no longer current.
  draftOutOfDate: boolean;
  othersInProgress: string[];
  finished: { draftId: string; reviewer: string; reviewedAt: string; verdicts: Record<string, Record<string, Verdict>>; evidence: Record<string, string> } | null;
  account: string;
  basedOn: "judge" | "severe review";
  basedOnReadingSha256: string;
  judgmentSha256: string;
  response: string;
  items: ReviewItem[];
}

type Problem = { kind: "conflict"; draft: StoredDraft } | { kind: "blocked" } | { kind: "changed" } | { kind: "refused"; error: string };

const target = (setup: ReviewSetup): { caseset: string; model: string; id: string; trial: number } => ({ caseset: setup.project, model: setup.model, id: setup.id, trial: setup.trial });
const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
const without = (all: Record<string, string>, key: string): Record<string, string> => Object.fromEntries(Object.entries(all).filter(([k]) => k !== key));

async function body(response: Response): Promise<Record<string, unknown>> {
  try { return await response.json() as Record<string, unknown>; } catch { return {}; }
}

async function sendDraft(setup: ReviewSetup, draft: Answers & { draftId: string; reviewer: string; judgmentSha256: string; basedOn: string; basedOnReadingSha256: string }, replacesRevision: number | null): Promise<SendResult> {
  let response: Response;
  try {
    response = await fetch(API, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: target(setup), draft, replacesRevision }) });
  } catch {
    return { kind: "retry", error: "No connection." };
  }
  return classifySave(response.status, await body(response));
}

function preselectedNote(carried: boolean, basedOn: ReviewData["basedOn"]): string {
  if (carried) return "Your last review's verdicts are preselected.";
  if (basedOn === "severe review") return "The severe review's verdicts are preselected.";
  return "The judge's verdicts are preselected.";
}

export default function JudgmentReview({ setup, onClose, onFinished }: { setup: ReviewSetup; onClose: () => void; onFinished: (result: FinishedReviewResult) => void }): ReactNode {
  const { reviewerId } = useReviewerId();
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<{ data: ReviewData } | { error: string } | null>(null);
  useEffect(() => {
    if (!reviewerId) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ caseset: setup.project, model: setup.model, id: setup.id, trial: String(setup.trial), reviewer: reviewerId });
    fetch(`${API}?${query}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const result = await body(response);
        if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : `The review could not be loaded (HTTP ${response.status}).`);
        setLoaded({ data: result as unknown as ReviewData });
      })
      .catch((error: Error) => { if (!controller.signal.aborted) setLoaded({ error: error.message === "Failed to fetch" ? "No connection. The review could not be loaded." : error.message }); });
    return () => controller.abort();
  }, [reviewerId, setup.project, setup.model, setup.id, setup.trial, attempt]);

  const reload = (): void => { setLoaded(null); setAttempt((n) => n + 1); };
  if (!loaded || !reviewerId) return <p className={styles.help} role="status">Loading the review.</p>;
  if ("error" in loaded) {
    return <div className={styles.notice} data-tone="bad" role="alert">
      <p>{loaded.error}</p>
      <span className={styles.tools}><button className={styles.button} type="button" onClick={reload}>Try again</button><button className={styles.button} type="button" onClick={onClose}>Close review</button></span>
    </div>;
  }
  return <ReviewEditor key={attempt} data={loaded.data} reviewer={reviewerId} setup={setup} onClose={onClose} onFinished={onFinished} onReload={reload} />;
}

function ReviewEditor({ data, reviewer, setup, onClose, onFinished, onReload }: {
  data: ReviewData; reviewer: string; setup: ReviewSetup; onClose: () => void; onFinished: (result: FinishedReviewResult) => void; onReload: () => void;
}): ReactNode {
  const name = useId();
  const staleDraft = data.draftOutOfDate ? data.draft : null;
  const current = staleDraft ? null : data.draft;
  const copyKey = browserCopyKey({ account: data.account, reviewer, project: setup.project, model: setup.model, id: setup.id, trial: setup.trial, judgmentSha256: data.judgmentSha256 });
  const carried = useMemo(() => carriedOver(data.finished, reviewer), [data.finished, reviewer]);
  const prior: Record<string, Verdict> = carried?.verdicts ?? {};
  const [answers, setAnswers] = useState<Answers>(() => current
    ? { verdicts: current.verdicts, evidence: current.evidence }
    : { verdicts: {}, evidence: carried?.evidence ?? {} });
  const [start] = useState(() => ({ draftId: current?.draftId ?? newDraftId(), revision: current?.revision ?? staleDraft?.revision ?? null }));
  const [restarting, setRestarting] = useState(staleDraft !== null);
  const [store] = useState(browserStore);
  // An unsaved browser copy is offered back, or set against a newer project save; editing waits for the choice.
  const [pending, setPending] = useState<{ kind: "offer" | "conflict"; copy: BrowserCopy } | null>(() => {
    const found = loadChoice(readCopy(store, copyKey), { draft: current, outOfDate: data.draftOutOfDate }, answers);
    return found.kind === "none" ? null : found;
  });
  const [saveState, setSaveState] = useState<SaverState>({ status: "idle", draftId: start.draftId, revision: start.revision, pending: false, error: null });
  const [problem, setProblem] = useState<Problem | null>(null);
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const answersRef = useRef(answers);
  const saverRef = useRef<DraftSaver<Answers> | null>(null);

  const now = (): string => new Date().toISOString();
  const side = (value: Answers, unsaved: boolean, draftId = saverRef.current?.draftId ?? start.draftId, serverRevision = saverRef.current?.revision ?? start.revision): CopySide => ({ verdicts: value.verdicts, evidence: value.evidence, draftId, serverRevision, unsaved });
  const show = (value: Answers): void => {
    answersRef.current = value;
    setAnswers(value);
    setItemErrors({});
  };

  useEffect(() => {
    const saver = new DraftSaver<Answers>({
      send: (draftId, replaces, value) => sendDraft(setup, {
        draftId, reviewer, judgmentSha256: data.judgmentSha256, basedOn: data.basedOn, basedOnReadingSha256: data.basedOnReadingSha256, ...value,
      }, replaces),
      onState: setSaveState,
      onSaved: (value, draftId, revision) => markSaved(store, copyKey, { ...value, draftId, serverRevision: revision }, now()),
      onProblem: (found: SaveProblem) => {
        if (found.kind === "conflict") setProblem(found.draft.judgmentSha256 === data.judgmentSha256 ? { kind: "conflict", draft: found.draft } : { kind: "blocked" });
        else setProblem(found.error === JUDGMENT_CHANGED ? { kind: "changed" } : { kind: "refused", error: found.error });
      },
      newDraftId,
    }, start.draftId, start.revision);
    saverRef.current = saver;
    const online = (): void => saver.retryNow();
    window.addEventListener("online", online);
    return () => { window.removeEventListener("online", online); saver.dispose(); };
    // The saver lives as long as this loaded draft; `key` on the editor remounts it for a reload.
  }, []);

  useEffect(() => {
    if (!saveState.pending && saveState.status !== "retrying" && saveState.status !== "stopped") return;
    const leave = (event: BeforeUnloadEvent): void => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [saveState.pending, saveState.status]);

  const update = (next: Answers): void => {
    answersRef.current = next;
    setAnswers(next);
    writeCopy(store, copyKey, { ...side(next, true), changedAt: now() });
    saverRef.current?.change(next);
  };

  const shownOf = (item: ReviewItem): Verdict => answers.verdicts[item.key] ?? prior[item.key] ?? preselected(item);
  const itemDone = (item: ReviewItem): boolean => Boolean(answers.verdicts[item.key])
    && verdictErrors([item], answers.verdicts, answers.evidence, data.response).length === 0;
  const reviewedVerdicts = Object.fromEntries(data.items.filter(itemDone).map((item) => [item.key, answers.verdicts[item.key]]));
  const counts = progress(data.items, reviewedVerdicts);
  const left = counts.total - counts.done;

  const choose = (item: ReviewItem, verdict: Verdict): void => {
    const latest = answersRef.current;
    if (latest.verdicts[item.key] === verdict) return;
    setItemErrors((all) => without(all, item.key));
    update({ ...latest, verdicts: { ...latest.verdicts, [item.key]: verdict } });
  };

  const takeSelection = (item: ReviewItem): void => {
    const pane = document.querySelector("[data-judgment-response]");
    const selection = window.getSelection();
    const range = selection && selection.rangeCount > 0 && !selection.isCollapsed ? selection.getRangeAt(0) : null;
    const inside = Boolean(range && pane?.contains(range.commonAncestorContainer));
    const quote = inside ? selection!.toString().trim() : "";
    const verdict = shownOf(item);
    const errors = range && !inside ? ["Select text inside the Response panel."]
      : verdictErrors([item], { [item.key]: verdict }, { [item.key]: quote }, data.response);
    if (errors.length) {
      setItemErrors((all) => ({ ...all, [item.key]: errors[0] }));
      return;
    }
    setItemErrors((all) => without(all, item.key));
    const latest = answersRef.current;
    update({ verdicts: { ...latest.verdicts, [item.key]: verdict }, evidence: { ...latest.evidence, [item.key]: quote } });
  };

  const startAgain = (): void => {
    moveAside(store, copyKey, now());
    setRestarting(false);
  };

  // The browser copy against the project's answers, chosen on load. The set not chosen is kept aside.
  const takeCopy = (copy: BrowserCopy): void => {
    chooseSet(store, copyKey, side(copy, true), side(answersRef.current, false), now());
    setPending(null);
    show({ verdicts: copy.verdicts, evidence: copy.evidence });
    saverRef.current?.change(answersRef.current);
  };

  const keepSaved = (copy: BrowserCopy): void => {
    chooseSet(store, copyKey, side(answersRef.current, false), { ...copy, unsaved: true }, now());
    setPending(null);
  };

  // A save raced another tab. This tab's answers stay unsaved in the copy until the project confirms them.
  const keepMine = (stored: StoredDraft): void => {
    chooseSet(store, copyKey, side(answersRef.current, true, stored.draftId, stored.revision), side(stored, false, stored.draftId, stored.revision), now());
    setProblem(null);
    saverRef.current?.change(answersRef.current);
    saverRef.current?.resume(stored.draftId, stored.revision, true);
  };

  const loadTheirs = (stored: StoredDraft): void => {
    chooseSet(store, copyKey, side(stored, false, stored.draftId, stored.revision), side(answersRef.current, true), now());
    show({ verdicts: stored.verdicts, evidence: stored.evidence });
    setProblem(null);
    saverRef.current?.resume(stored.draftId, stored.revision, false);
  };

  const finish = async (): Promise<void> => {
    const saver = saverRef.current;
    if (!saver) return;
    setFinishing(true);
    setFinishError(null);
    try {
      if (!await saver.flush() || saver.revision === null) {
        setFinishError("Finish waits until your answers are saved to the project. They are kept in this browser; try again once the status reads Saved.");
        return;
      }
      let response: Response;
      try {
        response = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: target(setup), reviewer, draftId: saver.draftId, draftRevision: saver.revision }) });
      } catch {
        setFinishError("No connection. The review is not finished yet. Press Finish again.");
        return;
      }
      const result = await body(response);
      if (response.ok) {
        writeCopy(store, copyKey, null);
        onFinished({ reviewedAt: String(result.reviewedAt) });
        return;
      }
      const error = typeof result.error === "string" ? result.error : `HTTP ${response.status}`;
      if (response.status === 409 && "draft" in result) {
        if (result.draft) setProblem({ kind: "conflict", draft: result.draft as StoredDraft });
        else {
          saver.resume(newDraftId(), null, false);
          update(answersRef.current);
          setFinishError("The saved draft was finished or removed in another tab. Your answers are being saved as a new draft. Press Finish again once the status reads Saved.");
        }
      } else if (error === JUDGMENT_CHANGED) setProblem({ kind: "changed" });
      else setFinishError(Array.isArray(result.errors) ? (result.errors as string[]).join(" ") : error);
    } finally {
      setFinishing(false);
    }
  };

  const statusText: Record<SaverState["status"], string> = { idle: "", saving: "Saving", saved: "Saved", retrying: "Not saved. Retrying.", stopped: "Not saved." };
  const locked = finishing || restarting || pending !== null || problem?.kind === "conflict";
  // Grouped from the review items, so every item shows even if the page's criterion list differs.
  const groups = [...new Set(data.items.map((item) => item.criterionId))].map((id) => {
    const criterion = setup.criteria.find((c) => c.id === id);
    return { id, question: criterion?.question ?? "Criterion", outsideRubric: criterion?.outsideRubric ?? false, items: data.items.filter((item) => item.criterionId === id) };
  });
  const view = (item: ReviewItem): ItemView => {
    const shown = shownOf(item);
    return {
      item, source: data.basedOn, shown, confirmed: Boolean(answers.verdicts[item.key]), priorVerdict: prior[item.key] ?? null,
      evidence: needsEvidence(item, shown) ? answers.evidence[item.key] ?? "" : "", error: itemErrors[item.key] ?? null, done: itemDone(item),
      evidenceKey: setup.evidenceKeys[item.judgeMatch?.evidence ?? ""] ?? setup.evidenceKeys[answers.evidence[item.key] ?? ""] ?? null,
    };
  };

  return <div className={styles.panel}>
    <div className={styles.bar}>
      <p>Reviewing as <strong>{reviewer}</strong>. <span>{counts.done} of {counts.total} items reviewed.</span></p>
      <span className={styles.tools}>
        <span className={styles.status} data-state={saveState.status} role="status" aria-live="polite">{statusText[saveState.status]}{saveState.error && saveState.status !== "saved" ? ` ${saveState.error}` : ""}</span>
        <Link className={styles.link} href={setup.caseHref} target="_blank" rel="noopener">Read the case</Link>
        <button className={styles.button} type="button" onClick={onClose}>Close review</button>
      </span>
    </div>

    {restarting && staleDraft && <div className={styles.notice} data-tone="bad" role="alert">
      <p>This judgment changed since you started. Start again from the current judgment.</p>
      <span className={styles.tools}><button className={styles.button} type="button" onClick={startAgain}>Start again</button></span>
    </div>}
    {pending && <div className={styles.notice} data-tone={pending.kind === "conflict" ? "bad" : undefined} role="alert">
      <p>{pending.kind === "offer" ? "This browser has answers that were not saved to the project." : "This browser has answers that were not saved, and the project has a newer save from another tab or window."}</p>
      <p>Last changed {pending.copy.changedAt.slice(0, 16).replace("T", " ")} UTC. Choose which answers to keep. The other set stays in this browser.</p>
      <span className={styles.tools}>
        <button className={styles.button} type="button" onClick={() => takeCopy(pending.copy)}>Use the browser copy</button>
        <button className={styles.button} type="button" onClick={() => keepSaved(pending.copy)}>{pending.kind === "offer" ? "Keep the saved answers" : "Keep the project's answers"}</button>
      </span>
    </div>}
    {problem?.kind === "conflict" && <div className={styles.notice} data-tone="bad" role="alert">
      <p>This review was also saved from another tab or window.</p>
      <p>Choose which answers to keep. The other set stays in this browser.</p>
      <span className={styles.tools}>
        <button className={styles.button} type="button" onClick={() => keepMine(problem.draft)}>Keep this tab's answers</button>
        <button className={styles.button} type="button" onClick={() => loadTheirs(problem.draft)}>Load the other tab's answers</button>
      </span>
    </div>}
    {problem?.kind === "changed" && <div className={styles.notice} data-tone="bad" role="alert">
      <p>{JUDGMENT_CHANGED}</p>
      <span className={styles.tools}><button className={styles.button} type="button" onClick={onReload}>Start again from the current judgment</button></span>
    </div>}
    {problem?.kind === "blocked" && <div className={styles.notice} data-tone="bad" role="alert">
      <p>An unfinished draft for the earlier judgment is still saved, so this review cannot be saved yet.</p>
      <p>Your answers are kept in this browser.</p>
    </div>}
    {problem?.kind === "refused" && <div className={styles.notice} data-tone="bad" role="alert"><p>Not saved: {problem.error}</p></div>}
    {data.othersInProgress.length > 0 && <p className={styles.notice}>In progress by {data.othersInProgress.join(", ")}.</p>}
    {!setup.rubricReviewed && <p className={styles.notice}>Rubric not yet reviewed. The score counts as reviewed only after the rubric is reviewed too.</p>}

    {!restarting && <>
      <p className={styles.help}>{preselectedNote(carried !== null, data.basedOn)}{data.finished && !carried ? ` The latest review, by ${data.finished.reviewer}, is not preselected.` : ""} Press a preselected verdict to confirm it, or choose another. Raising an item needs supporting text from the response.</p>
      <div className={listStyles.list}>
        {groups.map((group) => {
          const count = counts.byCriterion[group.id];
          return <section className={listStyles.row} key={group.id} aria-labelledby={`${name}-${group.id}`}>
            <div className={styles.criterionHead}>
              <span className={listStyles.question} id={`${name}-${group.id}`}><span className={listStyles.cid}>{group.id}</span>{group.question}</span>
              <span className={styles.count}>{count.done} of {count.total} reviewed</span>
            </div>
            {group.outsideRubric && <p className={styles.note}>Statements outside the rubric are not reviewed in this version.</p>}
            <ol className={styles.items}>
              {group.items.map((item) => <JudgmentReviewItem key={item.key} view={view(item)} name={`${name}-${item.key}`} locked={locked}
                onChoose={(verdict) => choose(item, verdict)} onUseSelection={() => takeSelection(item)} />)}
            </ol>
          </section>;
        })}
      </div>
      <div className={styles.finish}>
        {finishError ? <p className={styles.error} role="alert">{finishError}</p> : <p>Finishing records your verdicts and updates the score. The judge's reading stays on record.</p>}
        <button className={`${styles.button} ${styles.primary}`} type="button" disabled={left > 0 || locked || problem !== null} onClick={() => void finish()}>
          {left > 0 ? `${plural(left, "item", "items")} left` : finishing ? "Finishing" : "Finish review"}
        </button>
      </div>
    </>}
  </div>;
}
