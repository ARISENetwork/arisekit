import json
from pathlib import Path

import pytest

from arisekit.client import ModelResponse
from arisekit.images.image_generation import freeze_images, run_images, validate_brief
from arisekit.images.image_iteration import development_diagnosis, propose_image_revision, run_development_cycles, select_development_revision
from arisekit.images.image_validation import generation_report
from arisekit.images.imaging import ingest_collection
from test_imaging import ImageClient, brief, collection


class StyleWriter(ImageClient):
    def __call__(self, call):
        response = super().__call__(call)
        data = json.loads(response.text)
        payload = json.loads(call.item.prompt)
        data['question'] = f"{payload['question_style']}: classify this image using {payload['task_contract']['taxonomy']}."
        response.text = json.dumps(data)
        return response


def styled_run(root, *, role='development', answer='class one', pixel_seed=0):
    manifest, assets = collection(4 + pixel_seed, profiles=('classification',))
    manifest['records'] = manifest['records'][:4]
    assets = {name: assets[name] for row in manifest['records'] for name in row['images']}
    for row in manifest['records']:
        row['targets'][0].update(answer=answer, evidence='Private reference: ' + answer)
    ingest_collection(root / 'source', manifest, assets)
    config = brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
                   models=['vision-a', 'vision-b'], max_calls=48,
                   question_styles=['direct', 'selection'], evaluation_role=role)
    freeze_images(root, config)
    calls = []
    status = run_images(root, generator=StyleWriter('writer', calls), critic=ImageClient('reviewer', calls),
                        solvers={name: ImageClient(name, calls) for name in config['models']})
    assert status['status'] == 'complete'
    assert status['calls_total'] == len(calls) == 48
    return calls


@pytest.mark.parametrize('styles', [[], ['direct', 'direct'], ['invented'], 'direct', [True]])
def test_invalid_style_contracts_are_rejected(styles):
    with pytest.raises(ValueError, match='question styles'):
        validate_brief(brief(question_styles=styles))


def test_styles_do_not_silently_change_closed_vqa_evidence_policy():
    with pytest.raises(ValueError, match='match one classification or closed-vqa'):
        validate_brief(brief(question_styles=['direct']))


def test_every_image_gets_each_form_and_writer_has_no_pixels_or_reference(tmp_path):
    calls = styled_run(tmp_path)
    plan = json.loads((tmp_path / 'image-plan.json').read_text())
    by_source = {}
    for item in plan['originals']:
        by_source.setdefault(item['metadata']['source_id'], []).append(item)
    assert len(by_source) == 4
    for items in by_source.values():
        assert {item['metadata']['question_style'] for item in items} == {'direct', 'selection'}
        assert len({item['prompt'] for item in items}) == 1
        assert len({tuple(item['attachments']) for item in items}) == 1
    for model, call, images in calls:
        if model == 'writer':
            assert not images and not call.item.attachments
            payload = json.loads(call.item.prompt)
            assert set(payload['source_target']) == {'id', 'profile', 'choices'}
            assert payload['task_contract']['taxonomy'] == 'Synthetic fixture'
            assert payload['task_contract']['label_term'] == 'class'
            assert 'category' not in payload['style_instruction']
            assert 'Private reference' not in call.item.prompt
        else:
            assert images
    writer_contracts = {call.item.id: json.loads(call.item.prompt)['task_contract'] for model, call, _ in calls if model == 'writer'}
    for model, call, _ in calls:
        if model == 'reviewer':
            assert json.loads(call.item.prompt)['task_contract'] == writer_contracts[call.item.id]
    report = generation_report(tmp_path, bootstrap=20)
    assert report['profiles']['classification']['calibration']['unique_source_tasks'] == 4
    assert report['declared_contract_checks']['checked'] == 8
    assert report['declared_contract_checks']['structural_conflicts'] == 8
    assert report['declared_contract_checks']['ai_aligned_despite_structural_conflict'] == 8
    assert all(row['assigned_forms'] == row['distinct_wordings'] == 2
               for row in report['originality']['per_source_question_variation'])


def test_classification_writer_request_is_invariant_to_reference_and_pixels(tmp_path):
    from PIL import Image
    import io
    manifest, assets = collection(4, profiles=('classification',))
    requests = []
    for index, answer in enumerate(('class one', 'class two')):
        root = tmp_path / str(index)
        for row in manifest['records']:
            row['targets'][0].update(answer=answer, evidence=f'Private annotation {answer}')
        if index:
            for row in manifest['records']:
                stream = io.BytesIO()
                Image.new('RGB', (8, 8), (20 + len(requests), 40, 60)).save(stream, format='PNG')
                assets[row['images'][0]] = stream.getvalue()
        ingest_collection(root / 'source', manifest, assets)
        freeze_images(root, brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
            question_styles=['direct'], max_calls=16, evaluation_role='development'))
        from arisekit.images.image_generation import advance_images
        calls = []
        for _ in range(4):
            advance_images(root, generator=StyleWriter('writer', calls), critic=None, solvers={})
        requests.append(sorted(call.item.prompt for _, call, _ in calls))
    assert requests[0] == requests[1]


def set_calibration(root, *, preserve=False):
    path = root / 'image-results.json'
    results = json.loads(path.read_text())
    for step, row in results['completed'].items():
        if not step.startswith('solve:'):
            continue
        _, model, arm, identifier = step.split(':', 3)
        case = int(identifier.split('--')[0].split('-')[-1])
        correct = case < (4 if model == '0' else 2) if arm == 'original' or preserve else case < 3
        row['response'] = 'class one' if correct else 'class two'
    path.write_text(json.dumps(results))


def test_absolute_calibration_exposes_canceling_bias_and_collapsed_comparison(tmp_path):
    styled_run(tmp_path)
    set_calibration(tmp_path)
    values = generation_report(tmp_path, bootstrap=30)['profiles']['classification']
    assert values['mean_score_difference'] == 0
    calibration = values['calibration']
    assert calibration['mean_absolute_score_error'] == calibration['maximum_absolute_score_error'] == .25
    assert calibration['stable_comparison_outcomes'] == {'collapsed': 1}
    assert calibration['models'][1]['within_image_repeats']['original']['prediction_changes'] == 0
    assert calibration['repeatability_status'] == 'descriptive-repeated-forms'


def test_equal_calibration_errors_have_identical_selection_keys():
    from fractions import Fraction
    from arisekit.images.image_iteration import _calibration_key
    def panel(generated):
        return {'classification': {'models': [{'original': {'correct': a, 'assigned': 24},
            'generated': {'correct': b, 'assigned': 24}} for a, b in zip((16, 12, 14), generated)],
            'concordance': {'discordant': 0}}}
    assert _calibration_key(panel((18, 14, 14))) == _calibration_key(panel((14, 13, 13))) == (Fraction(1, 18), Fraction(1, 12), 0)


def test_development_selection_uses_calibration_and_retains_all_candidates(tmp_path):
    roots = [tmp_path / 'first', tmp_path / 'second']
    for root in roots:
        styled_run(root)
    set_calibration(roots[0])
    set_calibration(roots[1], preserve=True)
    selection = select_development_revision(roots)
    assert selection['selected']['run'] == str(roots[1])
    assert len(selection['candidates']) == 2
    assert selection['candidates'][0]['selection_key'][0] == .25
    assert selection['candidates'][1]['selection_key'][0] == 0


class ProposalClient:
    model = 'reviewer'

    def __init__(self):
        self.calls = []

    def __call__(self, call):
        self.calls.append(call)
        assert not call.item.attachments
        assert 'Private reference:' not in call.item.prompt and 'case-' not in call.item.prompt
        for contract in json.loads(call.item.prompt)['wording']['declared_contract_examples']:
            assert contract['task_contract']['choices'] == ['class one', 'class two']
            assert not {'answer', 'evidence', 'ground_truth', 'provenance'} & set(contract['task_contract'])
        assert 'vision-a' not in call.item.prompt
        return ModelResponse(text=json.dumps({'criteria': 'Retain taxonomy and whole-image scope; vary the requested form.',
            'diagnosis': 'Development calibration drift', 'changes': ['Preserve task scope']}), cost=.001, cost_known=True)


def test_revision_is_retained_and_never_infers_human_expert_ratings(tmp_path):
    root = tmp_path / 'development'
    styled_run(root)
    client = ProposalClient()
    proposal = propose_image_revision(root, tmp_path / 'proposal', client=client)
    assert proposal == propose_image_revision(root, tmp_path / 'proposal', client=client)
    assert len(client.calls) == 1
    feedback = json.loads(client.calls[0].item.prompt)
    metrics = feedback['profiles']['classification']['paired_score_diagnostics']
    assert metrics['leaderboard']['rbo']['tail_mass'] == pytest.approx(.9 ** 2)
    assert metrics == development_diagnosis(root)['profiles']['classification']['paired_score_diagnostics']
    assert not any(row['model'] in json.dumps(metrics) for row in development_diagnosis(root)['profiles']['classification']['models'])
    assert feedback['wording']['original_task_templates']
    assert {row['starts_with'] for row in feedback['wording']['declared_contract_examples']} == {None, 'Select'}
    assert feedback['wording']['declared_contract_checks']['structural_conflicts'] == 8
    assert len(feedback['wording']['generated_question_examples']) == 2
    assert development_diagnosis(root)['wording']['copied_original'] == 0
    assert generation_report(root, bootstrap=20)['expert_ratings_completed'] == 0


def test_historical_analysis_remains_available_but_dispatch_requires_frozen_runtime(tmp_path, monkeypatch):
    import arisekit.images.image_generation as generation
    import arisekit.images.image_validation as validation
    styled_run(tmp_path)
    monkeypatch.setattr(generation, '_runtime_hash', lambda: 'later-runtime')
    monkeypatch.setattr(validation, '_runtime_hash', lambda: 'later-runtime')
    with pytest.raises(ValueError, match='runtime changed'):
        generation.image_status(tmp_path)
    report = generation_report(tmp_path, bootstrap=20)
    assert not report['analysis_runtime_matches_generation']
    assert development_diagnosis(tmp_path)['parent_plan_sha256'] == report['plan_sha256']
    from arisekit.images.image_validation import export_review_packet
    assert export_review_packet(tmp_path, tmp_path / 'historical-review')['items'] == 16


def test_holdout_cannot_be_used_for_automatic_prompt_revision_or_selection(tmp_path):
    root = tmp_path / 'holdout'
    styled_run(root, role='holdout')
    client = ProposalClient()
    with pytest.raises(ValueError, match='development run'):
        propose_image_revision(root, tmp_path / 'proposal', client=client)
    with pytest.raises(ValueError, match='development run'):
        select_development_revision([root])
    assert not client.calls


def test_full_bounded_cycle_revises_and_resumes_without_paid_repetition(tmp_path):
    source = tmp_path / 'source'
    manifest, assets = collection(4, profiles=('classification',))
    ingest_collection(source, manifest, assets)
    calls = []
    class Critic(ImageClient):
        def __call__(self, call):
            if call.item.metadata['image_step'] == 'revise:criteria':
                self.calls.append((self.model, call, []))
                return ModelResponse(text=json.dumps({'criteria': 'Retain full taxonomy while varying sentence structure.',
                    'diagnosis': 'Preserve calibration', 'changes': ['Clear task context']}), cost=.001, cost_known=True)
            return super().__call__(call)
    clients = dict(generator=StyleWriter('writer', calls), critic=Critic('reviewer', calls),
                   solvers={name: ImageClient(name, calls) for name in ('vision-a', 'vision-b')})
    config = brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
        question_styles=['direct', 'selection'], evaluation_role='development',
        models=['vision-a', 'vision-b'], max_calls=48)
    result = run_development_cycles(tmp_path / 'cycles', source=source, brief=config, rounds=2, max_cost=2, **clients)
    assert result['status'] == 'complete'
    assert result['provider_calls'] == len(calls) == 97
    assert result['cost'] == pytest.approx(.097)
    assert len(result['candidates']) == 2
    assert result['selected']['eligible_novel_forms']
    assert 'Fewest lost stable-original comparisons' in result['rule']
    assert (tmp_path / 'cycles' / result['generator_policy']).exists()
    second = json.loads((tmp_path / 'cycles/round-2/image-plan.json').read_text())
    assert second['brief']['criteria'] == 'Retain full taxonomy while varying sentence structure.'
    assert second['brief']['max_cost'] == .9
    run_development_cycles(tmp_path / 'cycles', source=source, brief=config, rounds=2, max_cost=2, **clients)
    assert len(calls) == 97
    with pytest.raises(ValueError, match='cycle budget'):
        run_development_cycles(tmp_path / 'invalid', source=source, brief=config, rounds=2, max_cost=float('inf'), **clients)


@pytest.mark.parametrize('budget,accepted', [(1.65, True), (1.649999, False)])
def test_cycle_budget_uses_declared_decimal_amounts(tmp_path, monkeypatch, budget, accepted):
    import arisekit.images.image_iteration as iteration
    manifest, assets = collection(4, profiles=('classification',))
    source = tmp_path / 'source'
    ingest_collection(source, manifest, assets)
    config = brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
                   max_cost=.55, max_calls=24, evaluation_role='development')
    root = tmp_path / 'cycle'
    calls = []
    monkeypatch.setattr(iteration, 'run_images', lambda *args, **kwargs: calls.append('run') or {'status': 'stopped'})
    if accepted:
        result = run_development_cycles(root, source=source, brief=config, generator=None,
            critic=None, solvers={}, rounds=3, max_cost=budget)
        assert result['status'] == 'stopped'
        assert json.loads((root / 'cycle-plan.json').read_text())['max_cost'] == 1.65
        assert calls == ['run']
    else:
        with pytest.raises(ValueError, match='cycle budget'):
            run_development_cycles(root, source=source, brief=config, generator=None,
                critic=None, solvers={}, rounds=3, max_cost=budget)
        assert calls == [] and not (root / 'cycle-plan.json').exists()
