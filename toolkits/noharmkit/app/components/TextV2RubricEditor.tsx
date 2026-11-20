"use client";

import { useRouter } from "next/navigation";
import { useMemo, useRef, type ReactNode } from "react";
import RubricEditor, { type LoadedV2 } from "@/harmreview/components/RubricEditor";
import type { EditorStorage, Loaded as EditorLoaded } from "./AnswerTableEditor";
import type { TextV2EditorHost } from "./RubricEditorHost";
import { ReviewTag, Tag } from "./mc/ui";
import { FailedErrors, FailedTag } from "./runs/VersionFailure";
import { useReviewerId } from "@/lib/reviewer-id";
import type { ReviewState } from "@/lib/caseset/reviews";
import { savedNotice } from "@/lib/caseset/notice";
import { isTextV2, type TextV2Case } from "@/lib/rubric-text-v2";
import { validateTextV2ForDisplay } from "@/lib/text-v2-eligibility";

// The text rubric editor is noharm-science's rubric editor, synced into app/harmreview by tools/sync_harmreview.py.
// This wrapper supplies only what the toolkit knows: project storage, validation pinned to the project's judge
// contract, and its version, review and failure notices.
type Loaded = EditorLoaded<TextV2Case>;
type Hosted = LoadedV2 & Loaded;
// Storage plus Reset: the rubric a reviewed copy was based on, defaulting to load.
export type TextV2Storage = EditorStorage<TextV2Case> & { loadOriginal?: () => Promise<Loaded> };

interface EditorProps {
  caseId: string;
  source: { caseset: string; version: string };
  reviewState?: ReviewState;
  synthetic?: boolean;
  validationProvenance?: Record<string, unknown>;
}

const muted = "text-[hsl(var(--muted-foreground))]";
const tag = `rounded-md bg-[hsl(var(--muted))] px-2 py-0.5 text-[11px] font-semibold ${muted}`;

const hosted = (loaded: Loaded): Hosted => ({ ...loaded, provenance: { source: loaded.record, sourceFile: "", sourceRubricSha256: "" } });
function textV2Loaded(data: Loaded): Hosted {
  if (!isTextV2(data.record)) throw new Error("This version is not in the text rubric format. Reopen it from the Rubrics page.");
  return hosted(data);
}

export const RUBRIC_TUTORIAL_HREF = "/noharm/rubric-tutorial";

export default function TextV2RubricEditor(props: EditorProps): ReactNode {
  const router = useRouter();
  const { reviewerId } = useReviewerId();
  const { caseId, source: { caseset, version } } = props;
  const storage = useMemo<TextV2Storage>(() => {
    const endpoint = "/api/runs/table";
    const query = `&caseset=${encodeURIComponent(caseset)}&version=${encodeURIComponent(version)}`;
    const load = async (original: boolean): Promise<Loaded> => {
      const response = await fetch(`${endpoint}?caseId=${encodeURIComponent(caseId)}&reviewer=${encodeURIComponent(reviewerId ?? "")}${query}${original ? "&original=1" : ""}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Unable to load rubric.");
      return body as Loaded;
    };
    return {
      reviewerId,
      load: () => load(false),
      loadOriginal: () => load(true),
      save: async (request) => {
        const response = await fetch(endpoint, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
          caseId, reviewer: reviewerId, caseset, version, ...request,
        }) });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error);
        return body;
      },
      onSaved: () => router.refresh(),
    };
  }, [caseId, caseset, version, reviewerId, router]);
  return <TextV2RubricEditorView {...props} storage={storage} />;
}

interface Latest { source: EditorProps["source"]; reviewState?: ReviewState; synthetic: boolean; validationProvenance: Record<string, unknown> }

// The host the synced editor calls. Plain, so the save safeguards can be tested without React.
export function textV2Host(storage: TextV2Storage, latest: { current: Latest }, initial?: Loaded): TextV2EditorHost<Hosted> {
  return {
    reviewerId: storage.reviewerId,
    load: async () => textV2Loaded(await storage.load()),
    loadOriginal: async () => textV2Loaded(await (storage.loadOriginal ?? storage.load)()),
    save: async (loaded, timing) => {
      const body = await storage.save({ record: loaded.record, timing, sourceSha256: loaded.sourceSha256 ?? undefined, replacesSha256: loaded.replacesSha256 ?? null });
      const update = body.version
        ? { notice: savedNotice(body.version), ...(latest.current.source.version === body.version ? { sourceSha256: body.contentSha256 } : { replacesSha256: body.contentSha256 }) }
        : undefined;
      return { message: body.message ?? (body.version ? `Saved as ${body.version}` : "Saved"), ...(update ? { update } : {}) };
    },
    validate: (record) => validateTextV2ForDisplay(record, "draft", latest.current.validationProvenance),
    canSave: (loaded) => Boolean(storage.reviewerId) && loaded.canSave !== false,
    headerTags: (loaded) => {
      const { source: current, reviewState: state } = latest.current;
      return <>
        <span className={tag}>{current.version}</span>
        {state === "draft" ? <Tag tone="plain">Unreviewed</Tag> : state && <ReviewTag state={state} />}
        {loaded?.status === "failed" && <FailedTag />}
      </>;
    },
    banner: (loaded) => <>
      {latest.current.synthetic && <aside aria-label="Synthetic demo" className={`mb-3 rounded-md border border-[hsl(var(--border))] px-3.5 py-2 text-xs ${muted}`}><strong>Synthetic demo</strong>{" "}These inputs and outputs are illustrative, not clinically validated content.</aside>}
      {loaded.notice && <p className={`mb-3 text-xs ${muted}`} data-save-target>{loaded.notice}</p>}
      <p className={`mb-3 text-xs ${muted}`}>Edits save automatically to a separate reviewer copy. Saving does not establish clinical validation.</p>
      {loaded.status === "failed" && <FailedErrors errors={loaded.errors ?? []} reason={loaded.canSave === false ? loaded.cannotSaveReason : undefined} />}
    </>,
    tutorialHref: RUBRIC_TUTORIAL_HREF,
    ...(storage.saveLabel ? { saveLabel: storage.saveLabel } : {}),
    ...(storage.onSaved ? { onSaved: storage.onSaved } : {}),
    ...(storage.onDirtyChange ? { onDirtyChange: storage.onDirtyChange } : {}),
    ...(storage.onSavingChange ? { onSavingChange: storage.onSavingChange } : {}),
    ...(initial ? { initial: hosted(initial) } : {}),
  };
}

export function TextV2RubricEditorView({ caseId, source, reviewState, synthetic = false, validationProvenance = {}, storage, initial }: EditorProps & { storage: TextV2Storage; initial?: Loaded }): ReactNode {
  // The editor reloads when its host changes, so the host depends on storage alone and reads the rest when used.
  const latest = useRef({ source, reviewState, synthetic, validationProvenance });
  latest.current = { source, reviewState, synthetic, validationProvenance };
  const host = useMemo(() => textV2Host(storage, latest, initial), [storage, initial]);
  return <RubricEditor caseId={caseId} host={host} />;
}
