"""Offline integration through the real project command entrypoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import SYNTHETIC, tagged_synthetic_table

from pipeline.e2e import generate as generation
from pipeline.e2e import judge as judging
from pipeline.e2e import text_v2_runtime
from pipeline.e2e.project import Project
from pipeline.skillrun import SkillOutcome
from tools import noharm, run_inference
from arisekit.common.jsonio import read_jsonl


@pytest.mark.parametrize("trials", [1,3])
def test_real_cli_create_import_generate_collect_judge_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trials: int,
) -> None:
    project=tmp_path / "entrypoint-project"
    table=tagged_synthetic_table()
    complete={"decisions":{}, "offRubric":[]}
    evidence=[]
    for decision in table["decisions"]:
        row=next(row for row in decision["recommendations"] if row["score"]==7 and not row.get("parts"))
        evidence.append(row["text"])
        complete["decisions"][decision["id"]]={"recommended":[
            {"rowId":row["id"], "role":"first", "evidence":row["text"]}
        ]}
    response_files={"demo-complete":" ".join(evidence), "demo-incomplete":"No synthetic actions provided."}
    mappings={response_files["demo-complete"]:complete,
              response_files["demo-incomplete"]:{"decisions":{}, "offRubric":[]}}
    monkeypatch.setattr(noharm,"load_env",lambda:None)
    monkeypatch.setattr(run_inference,"load_env",lambda:None)
    def stage(*args: str) -> None:
        monkeypatch.setattr(sys,"argv",["noharm",*args])
        noharm.main()
    stage("create",str(project),"--trials",str(trials))
    Project(project).update_provenance(judge_scoring_source_commit=text_v2_runtime.CURRENT_COMMIT)
    stage("import",str(project),"--case","Syn002","--cases-dir",str(SYNTHETIC))
    def draft(name: str, variables: dict, backend: str, model: str, **kw: object) -> SkillOutcome:
        assert name==generation.SKILL
        assert kw["check"](table)==[]
        return SkillOutcome("pass",table,"synthetic draft",[],{"backend":"offline","model":"stub"})
    monkeypatch.setattr(generation,"run_skill",draft)
    stage("generate",str(project),"--case","Syn002","--runs","1","--format","answer-table")
    calls: list[tuple[str,str]]=[]
    def client(model: str):
        per_model=0
        def completion(prompt: str) -> tuple[str,int,dict]:
            nonlocal per_model
            selected=(per_model+(model=="second"))%2
            per_model+=1
            response=response_files["demo-incomplete" if selected else "demo-complete"]
            calls.append((model,response))
            return response,0,{}
        return completion
    monkeypatch.setattr(run_inference,"litellm_completion",client)
    monkeypatch.setattr(sys,"argv",["run_inference",str(project),"--model","first","--model","second"])
    run_inference.main()
    assert len(calls)==2*trials
    monkeypatch.setattr(run_inference,"litellm_completion",lambda model: lambda prompt: pytest.fail("resume made a request"))
    run_inference.main()
    assert len(calls)==2*trials
    def grade(name: str, variables: dict, backend: str, model: str, **kw: object) -> SkillOutcome:
        assert name==judging.SKILL
        output=mappings[variables["response"]]
        assert kw["check"](output)==[]
        return SkillOutcome("pass",output,"synthetic mapping",[],{"backend":"offline","model":"stub"})
    monkeypatch.setattr(judging,"run_skill",grade)
    stage("judge",str(project),"--workers","1")
    stage("score",str(project))
    assert (project / "results/report.md").is_file()
    for model in ["first","second"]:
        rows=read_jsonl(project / f"results/{model}_scored.jsonl")
        assert [row["trial"] for row in rows]==list(range(1,trials+1))
        expected=(1 if model=="first" else 0) if trials==1 else (2/3 if model=="first" else 1/3)
        assert sum(row["f1"] for row in rows)/trials==pytest.approx(expected)
    # A missing final trial must fail the same scoring entrypoint without replacing the report.
    if trials>1:
        responses=project / "results/responses/first.jsonl"
        rows=read_jsonl(responses)
        responses.write_text("".join(json.dumps(row)+"\n" for row in rows[:-1]))
        before=(project / "results/report.md").read_bytes()
        with pytest.raises(SystemExit) as exc:
            stage("score",str(project))
        assert exc.value.code==1 and (project / "results/report.md").read_bytes()==before
