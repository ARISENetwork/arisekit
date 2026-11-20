import json
from pathlib import Path

import pytest

from arisekit.client import ModelResponse
from arisekit.images.image_generation import advance_images, freeze_images, run_images, validate_brief
from arisekit.images.image_policy import _write_image_generator, apply_image_generator, load_image_generator
from arisekit.images.image_selection import select_comparison_preserving_revision
from arisekit.images.image_validation import export_review_packet, generation_report
from arisekit.images.imaging import digest
from arisekit.images import vqa_rad
from test_imaging import brief
from test_vqa_rad import fixture


class RepairClient:
    def __init__(self, model, calls, *, copied=True, remains_copy=False, failure=None):
        self.model, self.calls = model, calls
        self.copied, self.remains_copy, self.failure = copied, remains_copy, failure

    def __call__(self, call):
        step = call.item.metadata['image_step']
        self.calls.append((self.model, call))
        if step.startswith(('generate:', 'repair:')):
            payload = json.loads(call.item.prompt)
            assert not call.item.attachments
            assert not {'answer', 'ground_truth', 'human_paraphrase', 'reference'} & payload.keys()
            assert 'PRIVATE' not in call.item.prompt
            assert 'answer' not in payload['source_target']
            original = payload['task_contract']['original_question']
            direct = payload['question_style'] == 'clinical-direct'
            identifier = call.item.id.split('--')[0].split('-')[-1]
            question = (f'In this image, does the left lung show feature {identifier}?' if direct
                        else f'Can feature {identifier} be seen in the left lung?')
            if direct and ((step.startswith('generate:') and self.copied) or self.remains_copy):
                question = 'In this image, ' + original
            if step.startswith('repair:'):
                assert payload['candidate_question'] == 'In this image, ' + original
                if self.failure == 'timeout':
                    raise TimeoutError('Fixture timeout')
            text = json.dumps({'question': question, 'target_id': payload['source_target']['id'],
                'grounding': 'Synthetic engineering task fidelity', 'uncertainty': 'Not clinical evidence'})
        elif step.startswith('review:'):
            assert call.item.attachments
            text = json.dumps({'grounded': True, 'criteria_aligned': True, 'issues': [], 'uncertainty': 'Fixture'})
        else:
            assert call.item.attachments and call.item.ground_truth is None
            text = 'yes'
        return ModelResponse(text=text, cost=.001,
            cost_known=not (step.startswith('repair:') and self.failure == 'unknown-cost'),
            response_id=f'fixture-{len(self.calls)}')


def prepare(root, tmp_path, monkeypatch, *, answer_variant=False):
    rows, snapshot, index, assets = fixture(tmp_path, monkeypatch)
    for row in rows:
        row['question'] = f"Is feature {row['qid']} visible in the left lung?"
        if answer_variant:
            row['answer'] = 'No' if row['answer'] == 'Yes' else 'Yes'
            row['question_rephrase'] = 'PRIVATE modified human reference'
    snapshot.write_text(json.dumps(rows))
    monkeypatch.setattr(vqa_rad, 'SNAPSHOT_SHA256', digest(snapshot.read_bytes()))
    vqa_rad.connect_vqa_rad(root / 'source', snapshot=snapshot, image_index=index,
        question_ids=range(4), cache_dir=tmp_path / 'cache', fetch=lambda url: assets[url])
    config = brief(field='diagnostic radiology', profiles=['closed-vqa'], models=['solver'],
        case_count=4, evaluation_fraction=1, question_styles=['clinical-direct','clinical-alternate'],
        evaluation_role='development', max_calls=40, original_question_access=True, copy_repair_attempts=1)
    freeze_images(root, config)
    return config


def execute(root, calls, **kwargs):
    return run_images(root, generator=RepairClient('writer', calls, **kwargs),
        critic=RepairClient('reviewer', calls), solvers={'solver': RepairClient('solver', calls)})


@pytest.mark.parametrize('value', [-1, 2, True, '1'])
def test_repair_limit_is_explicitly_bounded(value):
    with pytest.raises(ValueError, match='zero or one'):
        validate_brief(brief(copy_repair_attempts=value))


def test_repair_requires_public_original_contract():
    with pytest.raises(ValueError, match='explicit original-question access'):
        validate_brief(brief(copy_repair_attempts=1))


def test_repair_is_retained_and_final_text_reaches_review_solver_and_package(tmp_path, monkeypatch):
    root = tmp_path / 'run'; prepare(root, tmp_path, monkeypatch)
    calls = []; status = execute(root, calls)
    assert status['status'] == 'complete' and status['completed_steps'] == 40
    assert status['calls_total'] == len(calls) == 36
    comparison = json.loads((root / 'comparison.json').read_text())
    repair = comparison['copy_repair']
    assert (repair['checks'], repair['model_requests'], repair['skipped']) == (8,4,4)
    assert sum(r['prefix_only_original_copy'] for r in repair['initial_originality']['per_task']) == 4
    assert not any(r['prefix_only_original_copy'] for r in comparison['originality']['per_task'])
    for model, call in calls:
        step = call.item.metadata['image_step']
        if '--form-clinical-direct' in step and (step.startswith('review:') or ':generated:' in step):
            text = json.loads(call.item.prompt)['solver_input']['question'] if model == 'reviewer' else call.item.prompt
            assert 'does the left lung show' in text
    results = json.loads((root / 'image-results.json').read_text())['completed']
    assert all('In this image, Is feature' in row['response'] for step,row in results.items()
               if step.startswith('generate:') and '--form-clinical-direct' in step)
    report = generation_report(root, bootstrap=10)
    assert report['copy_repair']['model_requests'] == 4
    assert report['declared_contract_checks']['structural_conflicts'] == 0
    assert execute(root, calls)['status'] == 'complete' and len(calls) == 36
    selected = select_comparison_preserving_revision([root])
    plan = json.loads((root/'image-plan.json').read_text())
    _write_image_generator(root/'policy.json',plan,cycle_plan_sha256='test',selection=selected)
    policy = load_image_generator(root/'policy.json')
    applied = apply_image_generator(policy,{**plan['brief'],'copy_repair_attempts':0})
    assert applied['copy_repair_attempts'] == 1
    packet = root/'review'; export_review_packet(root,packet)
    assert 'does the left lung show' in (packet/'reviewer/ratings.csv').read_text()


def test_unnecessary_checks_issue_no_requests_and_do_not_export_early(tmp_path, monkeypatch):
    root=tmp_path/'run';prepare(root,tmp_path,monkeypatch)
    calls=[]
    for _ in range(8):
        advance_images(root,generator=RepairClient('writer',calls,copied=False),critic=None,solvers={})
    with pytest.raises(ValueError,match='Finish the frozen copy repair check'):
        export_review_packet(root,root/'premature-review')
    status=execute(root,calls,copied=False)
    assert status['status']=='complete' and len(calls)==32
    assert json.loads((root/'comparison.json').read_text())['copy_repair']['skipped']==8


@pytest.mark.parametrize('failure',['unknown-cost','timeout'])
def test_unknown_repair_outcome_is_not_repeated(tmp_path,monkeypatch,failure):
    root=tmp_path/'run';prepare(root,tmp_path,monkeypatch)
    calls=[]
    assert execute(root,calls,failure=failure)['status']=='stopped'
    count=len(calls)
    assert sum(call.item.metadata['image_step'].startswith('repair:')for _,call in calls)==1
    assert execute(root,calls,failure=failure)['status']=='stopped' and len(calls)==count


def test_failed_rewrite_remains_a_copy_without_another_attempt(tmp_path,monkeypatch):
    root=tmp_path/'run';prepare(root,tmp_path,monkeypatch)
    calls=[];assert execute(root,calls,remains_copy=True)['status']=='complete'
    report=generation_report(root,bootstrap=10)
    assert sum(r['prefix_only_original_copy']for r in report['originality']['per_task'])==4
    assert select_comparison_preserving_revision([root],allow_no_selection=True)['selected']is None
    assert sum(call.item.metadata['image_step'].startswith('repair:')for _,call in calls)==4


def test_repair_prompt_is_invariant_to_hidden_answers_and_human_references(tmp_path,monkeypatch):
    prompts=[]
    for variant in (False,True):
        folder=tmp_path/str(variant);folder.mkdir();root=folder/'run'
        prepare(root,folder,monkeypatch,answer_variant=variant);calls=[];execute(root,calls)
        prompts.append([call.item.prompt for model,call in calls if call.item.metadata['image_step'].startswith('repair:')])
    assert prompts[0]==prompts[1]
