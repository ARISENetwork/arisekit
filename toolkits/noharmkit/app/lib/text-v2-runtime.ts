export const TEXT_V2_CURRENT_COMMIT = "d734383670f0e8251f46fc3e800038f2a46db0d6";
export const TEXT_V2_PIPELINE_V2_COMMIT = "c4c8091c486bd18fb83e76860c49f8d4b1666993";
export const TEXT_V2_LEGACY_COMMIT = "6d803fee097fef0040a58e017053b2e88238ef60";

export interface TextV2RuntimeBinding {
  judge_scoring_source_commit?: string;
  judge_protocol?: string;
  judge_contract_sha256?: string;
}

export function textV2JudgeProtocol(provenance: Record<string, unknown>): "J1" | "J2.2" | "J2.3" | "Unknown" {
  const commit = provenance.judge_scoring_source_commit;
  if (commit === TEXT_V2_PIPELINE_V2_COMMIT) return "J2.3";
  return commit === TEXT_V2_CURRENT_COMMIT ? "J2.2" : commit === undefined || commit === TEXT_V2_LEGACY_COMMIT ? "J1" : "Unknown";
}

export function textV2RuntimeCheck(provenance: Record<string, unknown>, record: TextV2RuntimeBinding): "current" | "unverified" | "mismatch" {
  const protocol = textV2JudgeProtocol(provenance);
  const recorded = [record.judge_scoring_source_commit, record.judge_protocol, record.judge_contract_sha256];
  if (protocol === "J1") return recorded.some(value => value !== undefined) ? "mismatch" : "current";
  if (protocol === "Unknown") return "mismatch";
  if (recorded.some(value => !value)) return "unverified";
  return record.judge_scoring_source_commit === (protocol === "J2.3" ? TEXT_V2_PIPELINE_V2_COMMIT : TEXT_V2_CURRENT_COMMIT) && record.judge_protocol === protocol && /^[a-f0-9]{64}$/.test(record.judge_contract_sha256!) ? "current" : "mismatch";
}
