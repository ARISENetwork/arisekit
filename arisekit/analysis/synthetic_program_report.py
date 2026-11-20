"""Program-level manifest for repeated real-versus-synthetic comparisons.

The public aggregation path replays every parity report from its exact input.
It does not combine comparison evidence into an omnibus verdict and does not
make a multiplicity claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from arisekit.archetype import (
    ArchetypeId,
    CLINICAL_VALIDITY_STATUS,
    SyntheticBenchmarkProgram,
)
from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.jsonio import strict_json_object
from arisekit.common.records import CanonicalRecord
from arisekit.common.validate import exact_fields as _fields
from arisekit.authoring.specialty import BenchmarkTrack
from arisekit.synthetic_parity import (
    ModelIdentity,
    ParityVerdict,
    SyntheticParityInput,
    SyntheticParityReport,
    replay_synthetic_parity_report,
)

PROGRAM_REPORT_SCHEMA_VERSION = "arisekit.synthetic-program-report.v2"
PROGRAM_REPORT_CLAIM_SCOPE = "comparison-level-structural-parity-only"
NO_OMNIBUS_VERDICT_STATUS = "not-defined-comparisons-remain-independent"
NO_MULTIPLICITY_CLAIM_STATUS = "not-assessed-no-joint-inference-claim"
REPRESENTATIVE_COUNT_STATUS = "descriptive-counts-only"
STRESS_RESULT_STATUS = "diagnostic-only"
ARTIFACT_HASH_KIND = "self-checksum-requires-external-byte-pin"


@dataclass(frozen=True, slots=True)
class SyntheticProgramReport(CanonicalRecord):
    """Complete, hash-bound manifest of one report per program comparison.

    ``program`` is required but is not duplicated in the serialized artifact.
    Its digest and the comparison-level bindings are serialized instead. The
    complete parity reports are embedded so loading can revalidate every report
    against the supplied exact program.

    Direct construction and loading validate artifact structure and program
    bindings only because neither operation receives parity inputs. Use
    :func:`aggregate_synthetic_program_reports` to create a report for an
    evidence-completion claim.
    """

    program: SyntheticBenchmarkProgram = field(repr=False, compare=False)
    reports: tuple[SyntheticParityReport, ...] = field(repr=False)
    schema_version: str = PROGRAM_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.program, SyntheticBenchmarkProgram):
            raise ValueError("program must be SyntheticBenchmarkProgram")
        if self.schema_version != PROGRAM_REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {PROGRAM_REPORT_SCHEMA_VERSION!r}"
            )

        supplied = tuple(self.reports)
        if not supplied or not all(
            isinstance(report, SyntheticParityReport) for report in supplied
        ):
            raise ValueError("reports must contain SyntheticParityReport values")

        comparison_ids = [report.comparison_id for report in supplied]
        if len(set(comparison_ids)) != len(comparison_ids):
            raise ValueError("program report contains duplicate comparison reports")

        expected_ids = [
            comparison.comparison_id for comparison in self.program.comparisons
        ]
        expected_set = set(expected_ids)
        actual_set = set(comparison_ids)
        if actual_set != expected_set:
            missing = sorted(expected_set - actual_set)
            extra = sorted(actual_set - expected_set)
            details: list[str] = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"unexpected {extra}")
            raise ValueError(
                "program report coverage must contain exactly one report per "
                f"comparison ({'; '.join(details)})"
            )

        by_comparison = {report.comparison_id: report for report in supplied}
        validated: list[SyntheticParityReport] = []
        for comparison_id in expected_ids:
            report = by_comparison[comparison_id]
            canonical_report = SyntheticParityReport.from_dict(report.to_dict())
            _validate_report_against_program(
                canonical_report,
                program=self.program,
                comparison_id=comparison_id,
            )
            validated.append(canonical_report)
        object.__setattr__(self, "reports", tuple(validated))

    @property
    def report_hashes(self) -> Mapping[str, str]:
        """Map each exact comparison ID to its preserved parity report hash."""

        return MappingProxyType(
            {report.comparison_id: report.digest for report in self.reports}
        )

    @property
    def representative_verdict_counts(self) -> Mapping[str, int]:
        """Return descriptive counts for representative comparisons only."""

        counts = {verdict.value: 0 for verdict in ParityVerdict}
        for report in self.reports:
            if report.track is BenchmarkTrack.REPRESENTATIVE:
                terminal = report.terminal_verdict
                if terminal is None:
                    raise ValueError(
                        "representative report is missing its terminal verdict"
                    )
                counts[terminal.value] += 1
        return MappingProxyType(counts)

    @property
    def representative_report_count(self) -> int:
        return sum(
            report.track is BenchmarkTrack.REPRESENTATIVE for report in self.reports
        )

    @property
    def stress_diagnostic_count(self) -> int:
        return sum(report.track is BenchmarkTrack.STRESS for report in self.reports)

    @property
    def program_verdict(self) -> None:
        """Program reports deliberately have no omnibus verdict."""

        return None

    @property
    def multiplicity_claim(self) -> None:
        """This manifest deliberately makes no joint-inference claim."""

        return None

    def _comparison_record(self, report: SyntheticParityReport) -> dict[str, Any]:
        comparison = self.program.comparison(report.comparison_id)
        terminal = report.terminal_verdict
        return {
            "comparison_id": report.comparison_id,
            "comparison_hash": comparison.digest,
            "registry_hash": report.registry_hash,
            "archetype_hash": report.archetype_hash,
            "evaluation_contract_hash": report.evaluation_contract_hash,
            "benchmark_archetype": report.benchmark_archetype,
            "specialty": report.specialty,
            "track": report.track.value,
            "endpoint": report.endpoint,
            "decision_rule_hash": report.decision_rule_hash,
            "model_panel": [model.to_dict() for model in report.model_panel],
            "report_hash": report.digest,
            "comparison_role": report.comparison_role,
            "overall_diagnostic_verdict": report.verdict.value,
            "terminal_verdict": (terminal.value if terminal is not None else None),
            "report": report.to_dict(),
        }

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program.program_id,
            "program_hash": self.program.digest,
            "registry_hash": self.program.registry_digest,
            "claim_scope": PROGRAM_REPORT_CLAIM_SCOPE,
            "clinical_validity_status": CLINICAL_VALIDITY_STATUS,
            "comparison_reports": [
                self._comparison_record(report) for report in self.reports
            ],
            "representative_report_count": self.representative_report_count,
            "representative_verdict_counts": dict(self.representative_verdict_counts),
            "representative_count_status": REPRESENTATIVE_COUNT_STATUS,
            "stress_diagnostic_count": self.stress_diagnostic_count,
            "stress_result_status": STRESS_RESULT_STATUS,
            "program_verdict": self.program_verdict,
            "program_verdict_status": NO_OMNIBUS_VERDICT_STATUS,
            "multiplicity_claim": self.multiplicity_claim,
            "multiplicity_claim_status": NO_MULTIPLICITY_CLAIM_STATUS,
            "artifact_hash_kind": ARTIFACT_HASH_KIND,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["artifact_hash"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        program: SyntheticBenchmarkProgram,
    ) -> "SyntheticProgramReport":
        """Load and revalidate an artifact against one exact program."""

        fields = {
            "schema_version",
            "program_id",
            "program_hash",
            "registry_hash",
            "claim_scope",
            "clinical_validity_status",
            "comparison_reports",
            "representative_report_count",
            "representative_verdict_counts",
            "representative_count_status",
            "stress_diagnostic_count",
            "stress_result_status",
            "program_verdict",
            "program_verdict_status",
            "multiplicity_claim",
            "multiplicity_claim_status",
            "artifact_hash_kind",
            "artifact_hash",
        }
        _fields(data, fields, "synthetic program report")
        if not isinstance(program, SyntheticBenchmarkProgram):
            raise ValueError("program must be SyntheticBenchmarkProgram")

        payload = {name: data[name] for name in fields - {"artifact_hash"}}
        if _digest(payload) != data["artifact_hash"]:
            raise ValueError("synthetic program report artifact hash mismatch")
        if data["program_id"] != program.program_id:
            raise ValueError(
                "synthetic program report program ID does not match supplied program"
            )
        if data["program_hash"] != program.digest:
            raise ValueError(
                "synthetic program report hash does not match supplied program"
            )
        if data["registry_hash"] != program.registry_digest:
            raise ValueError(
                "synthetic program report registry does not match supplied program"
            )

        records = data["comparison_reports"]
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise ValueError("comparison_reports must be a sequence")
        reports: list[SyntheticParityReport] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("comparison report record must be an object")
            _fields(
                record,
                {
                    "comparison_id",
                    "comparison_hash",
                    "registry_hash",
                    "archetype_hash",
                    "evaluation_contract_hash",
                    "benchmark_archetype",
                    "specialty",
                    "track",
                    "endpoint",
                    "decision_rule_hash",
                    "model_panel",
                    "report_hash",
                    "comparison_role",
                    "overall_diagnostic_verdict",
                    "terminal_verdict",
                    "report",
                },
                "comparison report record",
            )
            report = SyntheticParityReport.from_dict(record["report"])
            if record["report_hash"] != report.digest:
                raise ValueError("comparison record parity report hash mismatch")
            reports.append(report)

        result = cls(
            program=program,
            reports=tuple(reports),
            schema_version=data["schema_version"],
        )
        if result.to_dict() != dict(data):
            raise ValueError(
                "synthetic program report contains stale or non-derived fields"
            )
        return result

    @classmethod
    def from_json(
        cls,
        payload: str,
        *,
        program: SyntheticBenchmarkProgram,
    ) -> "SyntheticProgramReport":
        data = strict_json_object(payload, "synthetic program report")
        return cls.from_dict(data, program=program)

    @property
    def digest(self) -> str:
        return _digest(self._payload())


def aggregate_synthetic_program_reports(
    program: SyntheticBenchmarkProgram,
    evidence_pairs: Sequence[tuple[SyntheticParityInput, SyntheticParityReport]],
) -> SyntheticProgramReport:
    """Replay exact input/report pairs and build a complete program report."""

    if isinstance(evidence_pairs, (str, bytes)) or not isinstance(
        evidence_pairs, Sequence
    ):
        raise ValueError("evidence_pairs must be a sequence")

    reports: list[SyntheticParityReport] = []
    input_hashes: set[str] = set()
    for index, pair in enumerate(evidence_pairs):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(
                f"evidence pair {index} must be a two-item "
                "(SyntheticParityInput, SyntheticParityReport) tuple"
            )
        study, report = pair
        if not isinstance(study, SyntheticParityInput):
            raise ValueError(
                f"evidence pair {index} input must be SyntheticParityInput"
            )
        if not isinstance(report, SyntheticParityReport):
            raise ValueError(
                f"evidence pair {index} report must be SyntheticParityReport"
            )
        if study.digest != report.input_hash:
            raise ValueError(
                f"evidence pair {index} input digest does not match report input hash"
            )
        if study.comparison_id != report.comparison_id:
            raise ValueError(f"evidence pair {index} comparison IDs do not match")
        if study.digest in input_hashes:
            raise ValueError("evidence_pairs contain a duplicate parity input digest")
        input_hashes.add(study.digest)
        reports.append(
            replay_synthetic_parity_report(
                study,
                report,
                program=program,
            )
        )

    return SyntheticProgramReport(program=program, reports=tuple(reports))


def _validate_report_against_program(
    report: SyntheticParityReport,
    *,
    program: SyntheticBenchmarkProgram,
    comparison_id: str,
) -> None:
    comparison = program.comparison(comparison_id)
    archetype = program.registry.get(comparison.archetype_id)
    expected_panel = tuple(
        sorted(
            (
                ModelIdentity(
                    model_id=route.route_id,
                    model_family=route.family,
                )
                for route in program.solver_panel
            ),
            key=lambda model: model.model_id,
        )
    )
    checks = (
        ("program hash", report.program_hash, program.digest),
        ("comparison ID", report.comparison_id, comparison.comparison_id),
        ("registry hash", report.registry_hash, program.registry_digest),
        ("archetype hash", report.archetype_hash, archetype.digest),
        (
            "evaluation contract hash",
            report.evaluation_contract_hash,
            program.evaluation_contract_digest(comparison_id),
        ),
        (
            "benchmark archetype",
            report.benchmark_archetype,
            ArchetypeId(comparison.archetype_id).value,
        ),
        ("specialty", report.specialty, comparison.specialty_id),
        ("track", report.track, comparison.track),
        ("endpoint", report.endpoint, comparison.endpoint_id),
        (
            "decision rule hash",
            report.decision_rule_hash,
            comparison.decision_rule_hash,
        ),
        ("model panel", report.model_panel, expected_panel),
    )
    for label, actual, expected in checks:
        if actual != expected:
            raise ValueError(
                f"parity report {label} does not match program comparison "
                f"{comparison_id!r}"
            )
