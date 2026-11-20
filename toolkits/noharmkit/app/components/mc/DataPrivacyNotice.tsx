export default function DataPrivacyNotice() {
  return (
    <aside aria-labelledby="guide-data-privacy" className="scroll-mt-24 rounded-lg border border-mc-line bg-mc-surface p-5 text-sm leading-relaxed sm:p-6" id="data-privacy">
      <h2 className="m-0 text-lg font-semibold tracking-tight" id="guide-data-privacy">Data privacy</h2>
      <p className="mb-0 mt-2 text-mc-muted">Before using protected health information (PHI), ensure your data use, computing environment, coding agent, and model/provider routes are approved by your institution. Follow institutional privacy, security, and data-use policies. Otherwise, use synthetic data.</p>
      <p className="mb-0 mt-2 text-mc-muted">You are responsible for appropriate handling of PHI. NOHARMKit does not verify institutional approval or provide a compliant environment. Its authors and maintainers are not responsible for unauthorized or inappropriate use of PHI.</p>
    </aside>
  );
}
