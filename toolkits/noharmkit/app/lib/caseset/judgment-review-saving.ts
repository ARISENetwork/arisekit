import { BASE_NOT_ON_RECORD, JUDGMENT_CHANGED, JUDGMENT_NOT_CURRENT, REVIEW_ALREADY_FINISHED, type Verdict } from "@/lib/caseset/judgment-review";

export interface Answers { verdicts: Record<string, Verdict>; evidence: Record<string, string> }

// The draft a save raced, as the server stores it.
export interface StoredDraft extends Answers {
  draftId: string;
  revision: number;
  judgmentSha256: string;
  basedOn: "judge" | "severe review";
  basedOnReadingSha256: string;
  updatedAt: string;
}

export type SendResult =
  | { kind: "saved"; revision: number }
  // The stored draft is gone or finished: save the same answers as a new draft.
  | { kind: "restart" }
  | { kind: "conflict"; draft: StoredDraft }
  | { kind: "retry"; error: string }
  | { kind: "refused"; error: string };

// What a save response means. Refusals that cannot succeed on retry stop the saver and show their message.
export function classifySave(status: number, body: Record<string, unknown>): SendResult {
  const error = typeof body.error === "string" ? body.error : `HTTP ${status}`;
  if (status >= 200 && status < 300) return { kind: "saved", revision: body.revision as number };
  if (status === 409 && "draft" in body) return body.draft ? { kind: "conflict", draft: body.draft as StoredDraft } : { kind: "restart" };
  if (status === 409 && error === REVIEW_ALREADY_FINISHED) return { kind: "restart" };
  if ([JUDGMENT_CHANGED, JUDGMENT_NOT_CURRENT, BASE_NOT_ON_RECORD].includes(error)) return { kind: "refused", error };
  // A project-level save race that outlived the server's retry, or a server or connection fault.
  if (status === 409 || status === 408 || status === 429 || status >= 500) return { kind: "retry", error };
  return { kind: "refused", error };
}

export type SaveStatus = "idle" | "saving" | "saved" | "retrying" | "stopped";
// `error` is the last failed save's message, cleared by the next confirmed save.
export interface SaverState { status: SaveStatus; draftId: string; revision: number | null; pending: boolean; error: string | null }
export type SaveProblem = Extract<SendResult, { kind: "conflict" | "refused" }>;

type Timer = unknown;
export interface SaverOptions<T> {
  send: (draftId: string, replacesRevision: number | null, value: T) => Promise<SendResult>;
  onState: (state: SaverState) => void;
  // Called only after the project confirms a save of `value` and nothing newer is waiting.
  onSaved?: (value: T, draftId: string, revision: number) => void;
  onProblem: (problem: SaveProblem) => void;
  newDraftId: () => string;
  delay?: number;
  retryDelays?: number[];
  schedule?: (run: () => void, ms: number) => Timer;
  cancel?: (timer: Timer) => void;
}

// Autosave for one draft: the latest value goes out `delay` ms after the last change, one request at a time, and a
// newer value replaces any queued one. A failed send keeps its value queued, so nothing is dropped.
export class DraftSaver<T> {
  private queued: T | null = null;
  private sending = false;
  private stopped = false;
  private disposed = false;
  private failures = 0;
  private restarts = 0;
  private debounce: Timer | null = null;
  private retry: Timer | null = null;
  private waiters: Array<(saved: boolean) => void> = [];
  private state: SaverState;
  private readonly o: Required<SaverOptions<T>>;

  constructor(options: SaverOptions<T>, draftId: string, revision: number | null) {
    this.o = {
      onSaved: () => {}, delay: 3000, retryDelays: [2000, 5000, 10000, 30000],
      schedule: (run, ms) => setTimeout(run, ms), cancel: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
      ...options,
    };
    this.state = { status: "idle", draftId, revision, pending: false, error: null };
  }

  get draftId(): string { return this.state.draftId; }
  get revision(): number | null { return this.state.revision; }

  change(value: T): void {
    this.queued = value;
    this.clearDebounce();
    if (!this.stopped) this.debounce = this.o.schedule(() => { this.debounce = null; void this.pump(); }, this.o.delay);
    this.emit(this.stopped ? "stopped" : this.state.status === "retrying" ? "retrying" : "saving");
  }

  // Sends any queued value now; true once the latest value is confirmed saved.
  flush(): Promise<boolean> {
    if (this.stopped) return Promise.resolve(false);
    if (this.queued === null && !this.sending) return Promise.resolve(this.state.revision !== null);
    this.clearDebounce();
    const done = new Promise<boolean>((resolve) => this.waiters.push(resolve));
    void this.pump();
    return done;
  }

  retryNow(): void {
    if (this.retry === null) return;
    this.clearRetry();
    void this.pump();
  }

  // After a conflict: continue on the stored draft, sending this tab's queued answers (keep) or dropping them.
  // Dropping reports "saved" because the screen now shows the stored draft; it never calls onSaved.
  resume(draftId: string, revision: number | null, keep: boolean): void {
    this.stopped = false;
    this.restarts = 0;
    this.state = { ...this.state, draftId, revision, error: null };
    if (!keep) this.queued = null;
    if (this.queued !== null) void this.pump();
    else this.emit("saved");
  }

  // A queued value is still sent once, so leaving the page right after a change does not drop it.
  dispose(): void {
    this.clearDebounce();
    this.clearRetry();
    this.disposed = true;
    void this.pump();
  }

  private async pump(): Promise<void> {
    if (this.sending || this.stopped || this.queued === null) return;
    this.clearRetry();
    const value = this.queued;
    this.queued = null;
    this.sending = true;
    this.emit(this.state.status === "retrying" ? "retrying" : "saving");
    let result: SendResult;
    try {
      result = await this.o.send(this.state.draftId, this.state.revision, value);
    } catch (error) {
      result = { kind: "retry", error: (error as Error).message };
    }
    this.sending = false;
    if (result.kind === "saved") {
      this.failures = 0;
      this.restarts = 0;
      this.state = { ...this.state, revision: result.revision, error: null };
      if (this.queued !== null) {
        if (this.waiters.length || this.debounce === null) void this.pump();
        else this.emit("saving");
        return;
      }
      this.emit("saved");
      if (!this.disposed) this.o.onSaved(value, this.state.draftId, result.revision);
      this.settle(true);
      return;
    }
    this.queued ??= value;
    if (result.kind === "restart" && this.restarts < 2) {
      this.restarts += 1;
      this.state = { ...this.state, draftId: this.o.newDraftId(), revision: null };
      void this.pump();
      return;
    }
    if (result.kind === "retry") {
      this.failures += 1;
      this.state = { ...this.state, error: result.error };
      this.emit("retrying");
      this.settle(false);
      if (this.disposed) return;
      const wait = this.o.retryDelays[Math.min(this.failures, this.o.retryDelays.length) - 1];
      this.retry = this.o.schedule(() => { this.retry = null; void this.pump(); }, wait);
      return;
    }
    const problem: SaveProblem = result.kind === "restart" ? { kind: "refused", error: "The draft could not be started. Reload the page and try again." } : result;
    this.stopped = true;
    this.state = { ...this.state, error: problem.kind === "refused" ? problem.error : "This review was also saved from another tab or window." };
    this.emit("stopped");
    this.settle(false);
    this.o.onProblem(problem);
  }

  private clearDebounce(): void {
    if (this.debounce !== null) this.o.cancel(this.debounce);
    this.debounce = null;
  }

  private clearRetry(): void {
    if (this.retry !== null) this.o.cancel(this.retry);
    this.retry = null;
  }

  private settle(saved: boolean): void {
    const waiters = this.waiters;
    this.waiters = [];
    for (const resolve of waiters) resolve(saved);
  }

  private emit(status: SaveStatus): void {
    this.state = { ...this.state, status, pending: this.queued !== null || this.sending };
    if (!this.disposed) this.o.onState(this.state);
  }
}

// crypto.randomUUID needs a secure context; a tailnet http address is not one, but getRandomValues works everywhere.
export function newDraftId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
