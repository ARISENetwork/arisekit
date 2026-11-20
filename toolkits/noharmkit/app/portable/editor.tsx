import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { AnswerTableEditorView, type EditorStorage, type Loaded } from "../components/AnswerTableEditor";
import { TextV2RubricEditorView } from "../components/TextV2RubricEditor";
import { isTextV2, type TextV2Case } from "../lib/rubric-text-v2";
import type { AnswerTableCase } from "../lib/answer-table";
import type { PortableRubric } from "../lib/portable-review";
import { isValidReviewerId } from "../lib/clinician-review";
import { type PortableProjectReview, type PortableReview, type ProjectReviewPacket, type ReviewPacket } from "../lib/portable-review";
import { parsePortableProgress, renderPortableHtml, type PortableProgress } from "../lib/portable-html";
import "./editor.css";

const assignment = JSON.parse(document.getElementById("review-packet")!.textContent!) as ReviewPacket | ProjectReviewPacket;
const projectPacket = assignment.format === "noharm-project-review-packet-v1" ? assignment : null;
const packets = projectPacket ? projectPacket.packets : [assignment as ReviewPacket];

function restoreProgress(): { progress: PortableProgress | null; error: string } {
  const data = document.getElementById("review-progress");
  if (!data) return { progress: null, error: "" };
  try { return { progress: parsePortableProgress(JSON.parse(data.textContent!), assignment), error: "" }; }
  catch (cause) { return { progress: null, error: `Cannot reopen this saved review: ${(cause as Error).message}` }; }
}

const restored = restoreProgress();
const savedReview = restored.progress?.review;
const savedReviews = savedReview?.format === "noharm-project-expert-review-v1" ? savedReview.reviews : savedReview ? [savedReview] : [];

function download(review: PortableReview | PortableProjectReview, caseId: string): void {
  const html = renderPortableHtml(assignment, {
    js: document.getElementById("portable-runtime")!.textContent!,
    css: document.getElementById("portable-styles")!.textContent!,
    version: document.querySelector(".portable-version")!.textContent!,
  }, { review, caseId });
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  const name = review.format === "noharm-project-expert-review-v1" ? review.packet.project : review.packet.caseId;
  anchor.download = `${name}.reviewed-${review.reviewer}.html`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type Storage<Record> = EditorStorage<Record> & { loadOriginal?: () => Promise<Loaded<Record>> };
function storageFor<Record extends PortableRubric>(storage: Storage<PortableRubric>, matches: (record: PortableRubric) => record is Record): Storage<Record> {
  const checked = (load: () => Promise<Loaded<PortableRubric>>) => async (): Promise<Loaded<Record>> => {
    const loaded = await load();
    if (!matches(loaded.record)) throw new Error("The review rubric format does not match its editor.");
    return { ...loaded, record: loaded.record };
  };
  const { loadOriginal, ...rest } = storage;
  return { ...rest, load: checked(storage.load), ...(loadOriginal ? { loadOriginal: checked(loadOriginal) } : {}) };
}
const isAnswerTable = (record: PortableRubric): record is AnswerTableCase => !isTextV2(record);

function PortableEditor(): ReactNode {
  const [reviewer, setReviewer] = useState(savedReview?.reviewer ?? "");
  const [active, setActive] = useState<string | null>(savedReview?.reviewer ?? null);
  const [index, setIndex] = useState(restored.progress ? packets.findIndex((item) => item.caseId === restored.progress!.caseId) : 0);
  const copies = useRef<Record<string, PortableReview>>(Object.fromEntries(savedReviews.map((item) => [item.packet.caseId, item])));
  const [savedCount, setSavedCount] = useState(savedReviews.length);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [downloaded, setDownloaded] = useState(true);
  const [error, setError] = useState("");
  const packet = packets[index];
  const onDirtyChange = useCallback((value: boolean): void => { setDirty(value); if (value) setDownloaded(false); }, []);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent): void => { if (projectPacket && savedCount > 0 && !downloaded) event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [savedCount, downloaded]);

  const storage = useMemo<Storage<PortableRubric> | null>(() => {
    if (!active) return null;
    // Reset passes no saved copy, so the packet's own rubric comes back.
    const loadPacket = async (resumed: PortableReview | undefined): Promise<Loaded<PortableRubric>> => ({
      record: structuredClone(resumed?.record ?? packet.record), source: packet.source,
      fromCopy: Boolean(resumed), timing: resumed?.timing, status: "pass", errors: [], canSave: true,
      sourceSha256: packet.sourceSha256, replacesSha256: null,
      notice: projectPacket
        ? "Save this case, then download your review to keep or return your work. Reopen the downloaded file to continue."
        : "Download your review to keep or return your work. Reopen the downloaded file to continue.",
    });
    return {
    reviewerId: active,
    saveLabel: projectPacket ? "Save Case" : "Download Review",
    href: "#review",
    onDirtyChange,
    onSavingChange: setSaving,
    load: () => loadPacket(copies.current[packet.caseId]),
    loadOriginal: () => loadPacket(undefined),
    save: async ({ record, timing }) => {
      const review: PortableReview = { format: "noharm-expert-review-v1", packet, reviewer: active, record: structuredClone(record), timing: structuredClone(timing), savedAt: new Date().toISOString() };
      copies.current[packet.caseId] = review;
      if (!projectPacket) {
        download(review, packet.caseId);
        setDownloaded(true);
        return { message: "Review downloaded. Reopen that file to continue, or send it to the organizer." };
      }
      setSavedCount(Object.keys(copies.current).length);
      setDownloaded(false);
      return { message: "Case saved in this tab. Download Review to keep your work." };
    },
    };
  }, [active, packet, onDirtyChange]);

  const legacyStorage = useMemo(() => storage ? storageFor(storage, isAnswerTable) : null, [storage]);
  const textV2Storage = useMemo(() => storage ? storageFor<TextV2Case>(storage, isTextV2) : null, [storage]);

  const switchCase = (next: number): void => {
    setIndex(next);
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  };
  const downloadProject = (): void => {
    if (!projectPacket || !active) return;
    download({ format: "noharm-project-expert-review-v1", packet: projectPacket, reviewer: active,
      reviews: packets.flatMap((item) => copies.current[item.caseId] ? [copies.current[item.caseId]] : []), savedAt: new Date().toISOString() }, packet.caseId);
    setDownloaded(true);
  };

  if (restored.error) return <main className="portable-start"><h1>Expert rubric review</h1><p role="alert">{restored.error}</p></main>;
  if (storage) return <main id="review">
    {projectPacket && <section className="portable-project" aria-label="Project review navigation">
      <div className="portable-project-row">
        <strong>{assignment.project}</strong>
        <span aria-live="polite">{savedCount} of {packets.length} cases saved</span>
        <span>Reviewer: {active}</span>
        <button type="button" onClick={downloadProject} disabled={dirty || saving || savedCount === 0}>Download Review</button>
      </div>
      <nav className="portable-project-row" aria-label="Cases">
        <button type="button" onClick={() => switchCase(index - 1)} disabled={dirty || saving || index === 0}>Previous Case</button>
        <label>Case <select value={index} disabled={dirty || saving} onChange={(event) => switchCase(Number(event.target.value))}>
          {packets.map((item, i) => <option key={item.caseId} value={i}>{i + 1}. {item.caseId} ({copies.current[item.caseId] ? "saved" : "not saved"})</option>)}
        </select></label>
        <button type="button" onClick={() => switchCase(index + 1)} disabled={dirty || saving || index === packets.length - 1}>Next Case</button>
      </nav>
      <p role="status">{dirty ? "Save this case before switching or downloading." : savedCount === packets.length ? "All cases saved. Download your review to return to your organizer." : "Save each case, even if unchanged. Download partial progress and reopen that file to continue; every case must be saved before import."} {!downloaded && !dirty && "Changes are only in this tab until downloaded."}</p>
    </section>}
    {isTextV2(packet.record)
      ? <TextV2RubricEditorView key={packet.caseId} caseId={packet.caseId} source={{ caseset: packet.project, version: packet.version }} storage={textV2Storage!} synthetic={packet.synthetic} validationProvenance={packet.validationProvenance} />
      : <AnswerTableEditorView key={packet.caseId} caseId={packet.caseId} source={{ caseset: packet.project, version: packet.version }} storage={legacyStorage!} synthetic={packet.synthetic} />}
  </main>;
  return <main className="portable-start">
    <h1>Expert rubric review</h1>
    <p className="portable-assignment">{assignment.project} / {projectPacket ? `${packets.length} case${packets.length === 1 ? "" : "s"}` : packet.caseId}</p>
    <form onSubmit={(event) => { event.preventDefault(); if (!isValidReviewerId(reviewer)) { setError("Use 2-32 lowercase letters, numbers, or hyphens. Start with a letter or number."); return; } if (packets.some((item) => item.version === `reviewed-${reviewer}`)) { setError("Use a reviewer ID different from the source copy's reviewer to preserve that source."); return; } setActive(reviewer); setError(""); }}>
      <label htmlFor="reviewer">Reviewer ID</label>
      <input id="reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} autoComplete="off" required placeholder="e.g. expert-smith" />
      <button type="submit">Start Review</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </main>;
}

createRoot(document.getElementById("portable-editor")!).render(<PortableEditor />);
