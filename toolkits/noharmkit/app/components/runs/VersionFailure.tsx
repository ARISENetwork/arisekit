// Shared validation messages for the answer-table editor and response viewer.
export function FailedTag() {
  return (
    <span className="rounded-md border border-[hsl(var(--destructive))] px-2 py-0.5 text-[11px] font-semibold text-[hsl(var(--destructive))]">Failed</span>
  );
}

export function FailedErrors({ errors, reason }: { errors: string[]; reason?: string }) {
  return (
    <div className="mb-3" role="alert">
      <p className="mb-1 text-xs font-semibold text-[hsl(var(--destructive))]">This version failed validation. Fix the errors before saving.</p>
      {reason && <p className="mb-1 text-sm font-semibold text-[hsl(var(--destructive))]">{reason}</p>}
      {errors.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-[hsl(var(--destructive))]">
          {errors.map((error, i) => <li className="break-words" key={i}>{error}</li>)}
        </ul>
      )}
    </div>
  );
}
