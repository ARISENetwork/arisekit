interface Transition {
  skipTransition(): void;
  ready: Promise<void>;
  finished: Promise<void>;
}

// Wait for the destination to commit, rather than animating a stale DOM snapshot.
// Cancellation releases that wait and prevents a superseded callback navigating later.
export function navigationMotion(start: (update: () => Promise<void>) => Transition) {
  let pending: { target: string; release: () => void; cancel: () => void } | null = null;
  return {
    navigate(target: string, update: () => void): void {
      pending?.cancel();
      let cancelled = false;
      let release!: () => void;
      const committed = new Promise<void>((resolve) => { release = resolve; });
      const transition = start(async () => {
        if (cancelled) return;
        update();
        await committed;
      });
      const cancel = (): void => {
        cancelled = true;
        transition.skipTransition();
        release();
      };
      const entry = { target, release, cancel };
      pending = entry;
      // A slow or failed request must never leave the interface frozen.
      const timeout = setTimeout(() => { transition.skipTransition(); release(); }, 2000);
      void transition.ready.catch(() => {});
      void transition.finished.catch(() => {}).finally(() => {
        clearTimeout(timeout);
        if (pending === entry) pending = null;
      });
    },
    commit(target: string): boolean {
      if (pending?.target !== target) return false;
      pending.release();
      return true;
    },
    cancel(): void { pending?.cancel(); pending = null; },
  };
}
