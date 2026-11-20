import json
from copy import deepcopy

import pytest

from arisekit.client import ModelResponse
from arisekit.images.image_generation import freeze_images, run_images
from arisekit.images.image_iteration import run_development_cycles
from arisekit.images.image_policy import apply_image_generator, load_image_generator
from arisekit.images.image_validation import generation_report
from arisekit.images.imaging import ingest_collection
from test_image_iteration import StyleWriter
from test_imaging import ImageClient, brief, collection


def configuration(**changes):
    return brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
        question_styles=['direct', 'selection'], evaluation_role='development',
        models=['vision-a', 'vision-b'], max_calls=48, **changes)


@pytest.fixture
def learned_policy(tmp_path):
    manifest, assets = collection(4, profiles=('classification',))
    source = tmp_path / 'development-source'
    ingest_collection(source, manifest, assets)
    calls = []
    clients = dict(generator=StyleWriter('writer', calls), critic=ImageClient('reviewer', calls),
        solvers={name: ImageClient(name, calls) for name in ('vision-a', 'vision-b')})
    root = tmp_path / 'cycles'
    result = run_development_cycles(root, source=source, brief=configuration(), rounds=1, max_cost=1, **clients)
    assert result['status'] == 'complete'
    return root, load_image_generator(root / 'generator-policy.json'), clients, calls


def test_generator_transfers_without_development_cases_solver_panel_or_budget(tmp_path, learned_policy):
    root, policy, _, _ = learned_policy
    assert set(policy['configuration']) == {'criteria', 'profiles', 'question_styles', 'generator_model', 'critic_model'}
    assert all(value not in json.dumps(policy) for value in ('case-0', 'vision-a', 'case_count', 'ground_truth'))
    manifest, assets = collection(8, profiles=('classification',))
    manifest['records'] = manifest['records'][4:]
    manifest['source']['name'] = 'Second synthetic collection'
    for row in manifest['records']:
        row['field'] = 'second synthetic specialty'
    assets = {name: assets[name] for row in manifest['records'] for name in row['images']}
    target = tmp_path / 'evaluation'
    ingest_collection(target / 'source', manifest, assets)
    evaluation = configuration()
    evaluation.update(field='second synthetic specialty', seed='untouched-cohort', evaluation_role='holdout',
        generator_model='unused-writer', critic_model='unused-reviewer',
        models=['transfer-a', 'transfer-b'], max_calls=80, max_cost=.5, max_cost_per_call=.02,
        image_controls=['question-only'], original_question_access=False)
    applied = apply_image_generator(policy, evaluation)
    for key in ('field', 'seed', 'evaluation_role', 'models', 'max_calls', 'max_cost', 'max_cost_per_call', 'image_controls'):
        assert applied[key] == evaluation[key]
    assert 'original_question_access' not in applied
    assert applied['generator_model'] == 'writer' and applied['critic_model'] == 'reviewer'
    assert applied['generator_policy_sha256'] == policy['generator_sha256']
    assert evaluation['generator_model'] == 'unused-writer'
    workload = {key: value for key, value in evaluation.items()
        if key not in {'criteria', 'profiles', 'generator_model', 'critic_model', 'question_styles', 'original_question_access'}}
    assert apply_image_generator(policy, workload) == applied
    freeze_images(target, applied)
    plan = json.loads((target / 'image-plan.json').read_text())
    assert set(plan['selected_ids']) == {'case-4', 'case-5', 'case-6', 'case-7'}
    calls = []
    status = run_images(target, generator=StyleWriter('writer', calls), critic=ImageClient('reviewer', calls),
        solvers={name: ImageClient(name, calls) for name in evaluation['models']})
    assert status['status'] == 'complete'
    report = generation_report(target, bootstrap=20)
    assert report['generator_policy_sha256'] == policy['generator_sha256']
    assert report['evaluation_role'] == 'holdout' and report['expert_ratings_completed'] == 0


@pytest.mark.parametrize('change', [dict(criteria='Different question objective'), dict(generator_model='new-writer'),
                                   dict(question_styles=['assignment'])])
def test_changed_generator_cannot_keep_the_previous_identity(tmp_path, learned_policy, change):
    root, policy, clients, calls = learned_policy
    applied = apply_image_generator(policy, configuration())
    applied.update(change)
    with pytest.raises(ValueError, match='identity differs'):
        freeze_images(tmp_path / 'changed', applied)
    count = len(calls)
    with pytest.raises(ValueError, match='identity differs'):
        run_development_cycles(tmp_path / 'changed-cycle', source=root.parent / 'development-source',
            brief=applied, rounds=1, max_cost=1, **clients)
    assert len(calls) == count


def test_policy_checksum_and_runtime_changes_cannot_be_silently_accepted(learned_policy, monkeypatch):
    root, policy, _, _ = learned_policy
    import arisekit.images.image_policy as module
    monkeypatch.setattr(module, '_runtime_hash', lambda: 'different-runtime')
    with pytest.raises(ValueError, match='runtime changed'):
        apply_image_generator(policy, configuration())
    path = root / 'generator-policy.json'
    changed = deepcopy(policy)
    changed['configuration']['criteria'] = 'Altered'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='checksum'):
        load_image_generator(path)


def test_policy_cannot_silently_switch_task_profile(learned_policy):
    _, policy, _, _ = learned_policy
    evaluation = brief(profiles=['closed-vqa'])
    with pytest.raises(ValueError, match='same task profiles'):
        apply_image_generator(policy, evaluation)


def test_policy_cannot_override_the_evaluation_budget_or_solver_panel(learned_policy):
    _, policy, _, _ = learned_policy
    policy = deepcopy(policy)
    policy['configuration'].update(max_cost=100, models=['other-solver'])
    with pytest.raises(ValueError, match='exclude evaluation inputs'):
        apply_image_generator(policy, configuration())


def test_missing_policy_checksum_resumes_without_repeating_inference(learned_policy):
    root, policy, clients, calls = learned_policy
    (root / 'generator-policy.sha256.json').unlink()
    count = len(calls)
    result = run_development_cycles(root, source=root.parent / 'development-source', brief=configuration(),
        rounds=1, max_cost=1, **clients)
    assert result['generator_policy_sha256'] == policy['generator_sha256']
    assert len(calls) == count
    assert load_image_generator(root / 'generator-policy.json') == policy


class RevisionCritic(ImageClient):
    def __call__(self, call):
        if call.item.metadata['image_step'] == 'revise:criteria':
            self.calls.append((self.model, call, []))
            return ModelResponse(text=json.dumps({'criteria': 'Use different grammar for every requested form.',
                'diagnosis': 'Copied wording', 'changes': ['Vary grammar without changing the task']}), cost=.001, cost_known=True)
        return super().__call__(call)


class CopyWriter(StyleWriter):
    def __call__(self, call):
        result = super().__call__(call)
        value = json.loads(result.text)
        value['question'] = 'Which synthetic source class is assigned to this image?'
        result.text = json.dumps(value)
        return result


def test_new_revisions_keep_parent_lineage_without_reusing_the_parent_identity(learned_policy):
    root, policy, _, calls = learned_policy
    config = apply_image_generator(policy, configuration())
    destination = root.parent / 'next-generator'
    result = run_development_cycles(destination, source=root.parent / 'development-source', brief=config,
        rounds=2, max_cost=2, generator=StyleWriter('writer', calls), critic=RevisionCritic('reviewer', calls),
        solvers={name: ImageClient(name, calls) for name in config['models']})
    assert result['status'] == 'complete'
    cycle = json.loads((destination / 'cycle-plan.json').read_text())
    assert cycle['brief']['generator_policy_sha256'] == policy['generator_sha256']
    revised = json.loads((destination / 'round-2/image-plan.json').read_text())
    assert revised['brief']['criteria'] != policy['configuration']['criteria']
    assert 'generator_policy_sha256' not in revised['brief']


def test_all_copied_rounds_retain_diagnosis_and_never_export_a_winning_generator(tmp_path):
    manifest, assets = collection(4, profiles=('classification',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    calls = []
    clients = dict(generator=CopyWriter('writer', calls), critic=RevisionCritic('reviewer', calls),
        solvers={name: ImageClient(name, calls) for name in ('vision-a', 'vision-b')})
    result = run_development_cycles(tmp_path / 'cycles', source=tmp_path / 'source', brief=configuration(),
        rounds=2, max_cost=2, **clients)
    assert result['status'] == 'no-eligible-candidate' and result['selected'] is None
    assert len(result['candidates']) == 2 and not any(row['eligible_novel_forms'] for row in result['candidates'])
    assert result['provider_calls'] == len(calls) == 97
    assert not (tmp_path / 'cycles/generator-policy.json').exists()
    assert (tmp_path / 'cycles/round-1/diagnosis.json').exists()
    run_development_cycles(tmp_path / 'cycles', source=tmp_path / 'source', brief=configuration(),
        rounds=2, max_cost=2, **clients)
    assert len(calls) == 97


def test_revision_feedback_improves_generator_without_item_edits(tmp_path):
    manifest, assets = collection(4, profiles=('classification',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    calls = []
    class AdaptiveWriter(StyleWriter):
        def __call__(self, call):
            if 'Use different grammar' not in json.loads(call.item.prompt)['criteria']:
                return CopyWriter(self.model, self.calls)(call)
            return super().__call__(call)
    clients = dict(generator=AdaptiveWriter('writer', calls), critic=RevisionCritic('reviewer', calls),
        solvers={name: ImageClient(name, calls) for name in ('vision-a', 'vision-b')})
    result = run_development_cycles(tmp_path / 'cycles', source=tmp_path / 'source', brief=configuration(),
        rounds=2, max_cost=2, **clients)
    assert result['status'] == 'complete' and result['selected']['run'].endswith('round-2')
    assert not result['candidates'][0]['eligible_novel_forms'] and result['candidates'][1]['eligible_novel_forms']
    proposal = next(call for _, call, _ in calls if call.item.metadata['image_step'] == 'revise:criteria')
    assert json.loads(proposal.item.prompt)['wording']['copied_original'] == 8
    assert load_image_generator(tmp_path / 'cycles/generator-policy.json')['configuration']['criteria'] == 'Use different grammar for every requested form.'


def test_automatic_cycle_protects_stable_pairs_ahead_of_lower_calibration_error(tmp_path):
    manifest, assets = collection(4, profiles=('classification',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    calls = []
    class Solver:
        def __init__(self, model):
            self.model, self.count = model, 0
        def __call__(self, call):
            round_index = self.count // 16
            self.count += 1
            index = int(call.item.id.split('--')[0].split('-')[-1])
            original = call.item.metadata['image_step'].split(':')[2] == 'original'
            cutoff = (3 if self.model == 'vision-a' else 2) if original else (
                (1 if self.model == 'vision-a' else 0) if round_index == 0 else (2 if self.model == 'vision-a' else 3))
            calls.append((self.model, call, []))
            return ModelResponse(text='class one' if index < cutoff else 'class two', cost=.001, cost_known=True)
    result = run_development_cycles(tmp_path / 'cycles', source=tmp_path / 'source', brief=configuration(), rounds=2,
        max_cost=2, generator=StyleWriter('writer', calls), critic=RevisionCritic('reviewer', calls),
        solvers={name: Solver(name) for name in ('vision-a', 'vision-b')})
    assert result['selected']['run'].endswith('round-1')
    assert result['calibration_first_selection']['run'].endswith('round-2')
    assert result['candidates'][0]['selection_key'][0] == 0 and result['candidates'][1]['selection_key'][0] == 1
    assert result['candidates'][0]['selection_key'][1] > result['candidates'][1]['selection_key'][1]
    assert load_image_generator(tmp_path / 'cycles/generator-policy.json')['configuration']['criteria'] == configuration()['criteria']
