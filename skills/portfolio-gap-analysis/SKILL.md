---
name: arisekit/portfolio-gap-analysis
description: Routes sanitized MAST benchmark-fingerprint evidence into a clinical benchmark-design candidate, a portfolio-maintenance action, or a missing-result collection task. Use when a MAST operator asks where the benchmark portfolio is weak. Produces `portfolio-opportunity.md` and canonical `opportunity.json`.
---

# Portfolio gap analysis

Turn a released, sanitized fingerprint artifact into one defensible portfolio
action. Geometry is evidence, not a clinical need. Do not inspect or export raw
private benchmark items.

## What you produce

Use [`templates/portfolio-opportunity.template.md`](templates/portfolio-opportunity.template.md)
to write `portfolio-opportunity.md`, then serialize the same frozen record as
`opportunity.json` with `arisekit.authoring.opportunity.PortfolioOpportunity`.

## Conversation

1. When the released artifact is the MAST collection queue, import it with
   `load_portfolio_action_queue`. Require the exact expected file hash, analysis
   code hash, source revision, and evidence boundary. Preserve its rank,
   `action`, `target`, `rationale`, `utility`, and `cost`; do not manually
   restate or reorder rows.
2. Require an `EvidenceBoundary`: released-artifact hash, access class, reviewer,
   timestamp, and, for private-sanitized evidence, private-source and
   sanitization-code hashes. Stop if raw records or direct identifiers crossed
   the boundary.
3. Ask what signal was observed: conceptual coverage gap, redundancy,
   saturation, or missing result cells.
4. For a conceptual signal, require a frozen construct schema, a
   difficulty-and-model-ability baseline, residual analysis, permutation null,
   and distinct discovery and heldout confirmation splits. Freeze the statistic
   direction, discovery and heldout thresholds, maximum permutation p-value,
   and draw count before reading the heldout result. Record all hashes and
   observed statistics. A conceptual opportunity can serialize only if this
   frozen rule passes.
5. Route the signal without blending tracks:
   - coverage gap -> a proposed clinical need, then `arisekit/needs-analysis`;
   - redundancy or saturation -> portfolio maintenance, with a merge, retire,
     revise, or monitor action; do not invent a new clinical benchmark;
   - missing result cells -> result collection under a frozen collection
     protocol; do not require clinical-need or pilot-target fields.
6. For a coverage gap, make the clinical owner defend the need and provisional
   pilot targets. The fingerprint analysis may motivate the conversation but
   may not attest the need.
7. Write both artifacts and state the exact next route.

## Do not

- Do not turn a low-density embedding region into a clinical claim.
- Do not expose benchmark text, row identifiers, or reversible private labels.
- Do not route redundancy, saturation, or missing score cells into benchmark
  generation.
- Do not claim that this planning record admits a benchmark to MAST.

## Upstream artifacts

- Sanitized fingerprint release and evidence-boundary record.
- Optional `PortfolioActionQueue` imported from the released MAST collection
  queue; it remains upstream evidence rather than a clinical attestation.
- Frozen construct schema and result-matrix snapshot.

## Downstream readers

- `arisekit/needs-analysis` for a coverage-gap candidate.
- MAST portfolio maintainers for redundancy or saturation.
- The benchmark runner for missing-result collection.
- `arisekit.package.write_package`, which can preserve `opportunity.json`.
