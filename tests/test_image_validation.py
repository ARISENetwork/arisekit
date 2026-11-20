from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import random
import zipfile

import pytest


from arisekit.images.image_generation import advance_images, freeze_images, run_images, validate_brief
from arisekit.images.image_validation import export_review_packet, generation_report, kendall_tau_b
from arisekit.images.imaging import ingest_collection
from arisekit.dispatch import DispatchLedger
from arisekit.runner import RunnerConfig
from test_imaging import ImageClient, brief, collection


def test_pooled_score_ties_do_not_become_ordering_from_float_roundoff():
    from arisekit.images.image_validation import _calibration_and_forms
    from arisekit.types import BenchmarkItem
    styles = ('direct', 'selection')
    items = [BenchmarkItem(id=f'{style}-{i}', prompt='Classify the image.',
        metadata={'source_id': str(i), 'target_id': 'label', 'question_style': style})
        for style in styles for i in range(12)]
    rows = []
    for model, original, generated in (('a', (10, 10), (8, 9)), ('b', (9, 9), (7, 10))):
        scores = {arm: [{'correct': int(i < count), 'valid': True,
            'answer': 'correct' if i < count else 'incorrect'}
            for count in counts for i in range(12)]
            for arm, counts in (('original', original), ('generated', generated))}
        rows.append({'model': model, 'scores': scores, **{arm: {'correct': sum(counts),
            'assigned': 24, 'accuracy': sum(counts) / 24, 'missing': 0}
            for arm, counts in (('original', original), ('generated', generated))}})
    assert _calibration_and_forms(items, rows)['stable_comparison_outcomes'] == {'collapsed': 1}


def test_declared_contract_checks_find_style_and_whole_term_conflicts():
    from arisekit.images.image_validation import contract_diagnostics, _contract_report
    contract = {'task_contract': {'required_terms': ['BreastMNIST', 'ultrasound', 'class', 'released']},
        'starts_with': 'Select', 'ends_with_question_mark': False}
    checks = contract_diagnostics('Determine the classification of this BreastMNIST ultrasound image.', contract)
    assert checks['missing_required_terms'] == ['class', 'released']
    assert checks['start_rule_satisfied'] is False
    assert contract_diagnostics('Select the released BreastMNIST class for this ultrasound image.', contract) == {
        'missing_required_terms': [], 'start_rule_satisfied': True, 'question_mark_rule_satisfied': True}
    assert _contract_report({'brief': {'question_styles': ['selection']}}, {}) == {'status': 'not-frozen-in-plan', 'checked': 0}


@pytest.mark.parametrize('x,y,expected', [
    ([0, 1, 2], [0, 1, 2], 1), ([0, 1, 2], [2, 1, 0], -1),
    ([0, 0, 1], [0, 1, 1], .5), ([1, 1, 1], [0, 1, 2], None),
])
def test_kendall_respects_ties_and_undefined_arms(x, y, expected):
    assert kendall_tau_b(x, y)['tau_b'] == expected


def test_kendall_matches_scipy_on_tied_model_panels():
    scipy = pytest.importorskip('scipy.stats')
    rng = random.Random(24)
    for _ in range(100):
        x, y = [[rng.randrange(5) for _ in range(6)] for _ in range(2)]
        expected = scipy.kendalltau(x, y).statistic
        actual = kendall_tau_b(x, y)['tau_b']
        assert actual == pytest.approx(expected) if actual is not None else expected != expected


def test_retained_generation_seed_preserves_cost_and_call_accounting(tmp_path):
    from arisekit.images.image_generation import _usage
    path = tmp_path / 'image-dispatch.jsonl'
    ledger = DispatchLedger(path, RunnerConfig(max_cost=1, max_cost_per_call=.025, require_known_cost=True),
                            {('generate:retained-item', 1): {'cost': .002, 'provider_calls': 1, 'cost_unknown': False}})
    ledger.close()
    assert _usage(tmp_path) == {'cost': .002, 'provider_calls': 1, 'cost_unknown': False}


def finished_run(tmp_path, *, cohort=False):
    manifest, assets = collection(4, profiles=('classification',))
    if cohort:
        for row in manifest['records']:
            row['group_id'] = 'unresolved-patients'
            row['group_basis'] = 'conservative-cohort'
    ingest_collection(tmp_path / 'source', manifest, assets)
    config = brief(profiles=['classification'], case_count=4, evaluation_fraction=1,
                   models=['vision-a', 'vision-b'], max_calls=24)
    status = freeze_images(tmp_path, config)
    calls = []
    writer, reviewer = ImageClient('writer', calls), ImageClient('reviewer', calls)
    models = {name: ImageClient(name, calls) for name in config['models']}
    while status['next_step']:
        status = advance_images(tmp_path, generator=writer, critic=reviewer, solvers=models)
        assert status['status'] != 'stopped'
    return calls


def test_report_marks_all_tied_panel_and_cohort_uncertainty(tmp_path):
    finished_run(tmp_path, cohort=True)
    report = generation_report(tmp_path, bootstrap=50)
    result = report['profiles']['classification']
    assert result['ranking_status'] == 'undefined-all-tied-arm'
    assert result['concordance']['tau_b'] is None
    assert result['concordance']['tied_both'] == 1
    assert result['model_bootstrap']['undefined'] == 50
    assert result['model_bootstrap']['percentile_95'] is None
    assert result['group_bootstrap']['requested'] == 0
    assert result['source_groups'] == 1
    assert result['lin_ccc'] is None
    assert report['expert_ratings_completed'] == 0
    assert 'pending' in report['claim_status']
    assert report == generation_report(tmp_path, bootstrap=50)


def test_incomplete_panel_cannot_look_like_rank_evidence(tmp_path):
    finished_run(tmp_path)
    path = tmp_path / 'image-results.json'
    records = json.loads(path.read_text())
    key = next(key for key in records['completed'] if key.startswith('solve:1:generated:'))
    del records['completed'][key]
    path.write_text(json.dumps(records))
    result = generation_report(tmp_path, bootstrap=20)['profiles']['classification']
    assert result['ranking_status'] == 'incomplete-model-data'
    assert result['concordance'] is None
    assert result['paired_score_diagnostics'] is None
    assert result['lin_ccc'] is None
    assert result['models'][1]['generated']['missing'] == 1
    assert result['models'][1]['generated']['accuracy'] == .75


def test_paired_scores_bias_and_resampling_use_retained_answers(tmp_path):
    finished_run(tmp_path)
    path = tmp_path / 'image-results.json'
    records = json.loads(path.read_text())
    for index, arm, correct in [(0, 'original', 4), (0, 'generated', 3), (1, 'original', 2), (1, 'generated', 1)]:
        keys = sorted(key for key in records['completed'] if key.startswith(f'solve:{index}:{arm}:'))
        for position, key in enumerate(keys):
            records['completed'][key]['response'] = 'class one' if position < correct else 'class two'
    path.write_text(json.dumps(records))
    result = generation_report(tmp_path, bootstrap=100)['profiles']['classification']
    assert result['concordance']['tau_b'] == 1
    assert result['lin_ccc'] == pytest.approx(2 / 3)
    assert result['mean_score_difference'] == -.25
    assert result['models'][0]['prediction_changes'] == 1
    assert result['models'][0]['paired_correctness'] == {'1->1': 3, '1->0': 1}
    assert result['model_bootstrap']['defined'] + result['model_bootstrap']['undefined'] == 100
    assert result['model_bootstrap']['undefined'] > 0
    assert result['group_bootstrap']['requested'] == 100
    assert result['source_groups'] == 4


def test_writer_isolated_from_original_question_and_six_models_are_supported(tmp_path):
    models = [f'vision-{index}' for index in range(6)]
    assert validate_brief(brief(models=models))['models'] == models
    with pytest.raises(ValueError, match='1–20'):
        validate_brief(brief(models=[f'vision-{index}' for index in range(21)]))
    calls = finished_run(tmp_path)
    for _, call, _ in calls:
        if call.item.metadata['image_step'].startswith('generate:'):
            target = json.loads(call.item.prompt)['source_target']
            assert 'question' not in target and 'question_origin' not in target
            assert set(target) == {'id', 'profile', 'choices'}


def test_reviewer_reference_is_separate_from_exact_solver_input(tmp_path):
    calls = finished_run(tmp_path)
    source = json.loads((tmp_path / 'source' / 'source.json').read_text())
    targets = {row['id']: row['targets'][0] for row in source['records']}
    solvers = {call.item.id: call for model, call, _ in calls
               if model == 'vision-a' and call.item.metadata['image_step'].startswith('solve:0:generated:')}
    for _, call, _ in calls:
        step = call.item.metadata['image_step']
        if step.startswith('generate:'):
            data = json.loads(call.item.prompt)
            assert data['solver_input']['choices'] == ['class one', 'class two']
            assert data['solver_input']['other_context'] == 'None'
            assert 'earlier_question_wording' not in data
        if step.startswith('review:'):
            data = json.loads(call.item.prompt)
            solver = solvers[call.item.id]
            assert data['solver_input']['question'] == solver.item.prompt
            target = targets[call.item.id.split('--')[0]]
            assert data['task_definition'] == {key: target[key] for key in ('id', 'profile', 'choices')}
            assert 'reviewer_only_reference' not in data
            assert call.item.attachments == solver.item.attachments
            assert solver.item.ground_truth is None
            assert set(solver.item.metadata) == {'image_step', 'image_condition', 'response_schema'}


def test_classification_writer_and_critic_inputs_do_not_depend_on_reference_answer(tmp_path):
    calls = []
    for index, answer in enumerate(('class one', 'class two')):
        root = tmp_path / str(index)
        manifest, assets = collection(2, profiles=('classification',))
        for row in manifest['records']:
            row['targets'][0].update(answer=answer, evidence=f'Private annotation says {answer}')
        ingest_collection(root / 'source', manifest, assets)
        freeze_images(root, brief(profiles=['classification'], evaluation_fraction=1))
        current = []
        for _ in range(4):
            advance_images(root, generator=ImageClient('writer', current), critic=ImageClient('reviewer', current), solvers={})
        calls.append([(model, call.item.prompt, call.system_prompt, images) for model, call, images in current])
    assert calls[0] == calls[1]


def test_closed_vqa_retains_its_distinct_reference_evidence_policy(tmp_path):
    manifest, assets = collection(2, profiles=('closed-vqa',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    freeze_images(tmp_path, brief(profiles=['closed-vqa'], evaluation_fraction=1))
    calls = []
    for _ in range(4):
        advance_images(tmp_path, generator=ImageClient('writer', calls), critic=ImageClient('reviewer', calls), solvers={})
    writer = json.loads(calls[0][1].item.prompt)['source_target']
    reviewer = json.loads(calls[2][1].item.prompt)['reviewer_only_reference']
    assert writer['answer'] == reviewer['answer'] == 'class one'
    assert 'evidence' in writer and 'evidence' in reviewer


def test_automatic_run_resumes_partial_work_without_repeating_calls(tmp_path):
    manifest, assets = collection(2, profiles=('classification',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    freeze_images(tmp_path, brief(profiles=['classification'], evaluation_fraction=1))
    calls = []
    clients = dict(generator=ImageClient('writer', calls), critic=ImageClient('reviewer', calls),
                   solvers={'vision': ImageClient('vision', calls)})
    advance_images(tmp_path, **clients)
    advance_images(tmp_path, **clients)
    status = run_images(tmp_path, **clients)
    assert status['status'] == 'complete'
    assert len(calls) == status['calls_total'] == 8
    run_images(tmp_path, **clients)
    assert len(calls) == 8


def test_automatic_run_stops_on_invalid_generation_and_preserves_paid_response(tmp_path):
    manifest, assets = collection(2, profiles=('classification',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    freeze_images(tmp_path, brief(profiles=['classification'], evaluation_fraction=1))
    calls = []
    clients = dict(generator=ImageClient('writer', calls, invalid=True), critic=None, solvers={})
    status = run_images(tmp_path, **clients)
    assert status['status'] == 'stopped'
    assert status['calls_total'] == len(calls) == 1
    assert next((tmp_path / 'responses').glob('*.json')).is_file()
    run_images(tmp_path, **clients)
    assert len(calls) == 1
    from arisekit.images.image_generation import main
    with pytest.raises(SystemExit) as stopped:
        main(['run', str(tmp_path)])
    assert stopped.value.code == 1
    assert len(calls) == 1


def test_blinded_packet_has_no_arm_reference_or_source_ids_and_no_fake_ratings(tmp_path):
    run = tmp_path / 'run'
    finished_run(run)
    exported = export_review_packet(run, tmp_path / 'export')
    mapping = json.loads(Path(exported['private_mapping']).read_text())
    assert len(mapping['items']) == exported['items'] == 8
    with zipfile.ZipFile(exported['archive']) as archive:
        assert all(not name.startswith('private/') for name in archive.namelist())
        assert 'license: CC0' in archive.read('SOURCE.txt').decode()
        rows = list(csv.DictReader(io.StringIO(archive.read('ratings.csv').decode())))
        assert len(rows) == 8
        for row in rows:
            assert not {'arm', 'source_reference', 'source_item_id'} & set(row)
            assert row['expert_answer'] == row['provenance_guess'] == ''
            assert 'case-' not in row['image_paths']
            assert archive.read(row['image_paths'])
        assert all(row['source_reference'] == 'class one' for row in mapping['items'])
        assert len({row['review_item_id'] for row in rows}) == 8
        assert {row['review_item_id'] for row in rows} == {row['review_item_id'] for row in mapping['items']}
    with pytest.raises(ValueError, match='already exists'):
        export_review_packet(run, tmp_path / 'export')


def test_analysis_settings_and_both_source_files_are_bound_without_changing_run(tmp_path):
    from arisekit.images.imaging import digest
    import arisekit.images.image_validation as analysis_module
    finished_run(tmp_path)
    plan_bytes = (tmp_path / 'image-plan.json').read_bytes()
    records_bytes = (tmp_path / 'image-results.json').read_bytes()
    a = generation_report(tmp_path, bootstrap=2)
    b = generation_report(tmp_path, bootstrap=2, analysis={'rbo_p': .8, 'coverage_tolerance_pp': 5})
    assert a['analysis_settings_sha256'] != b['analysis_settings_sha256']
    assert a['analysis_sha256'] == b['analysis_sha256'] == digest({
        name: digest((Path(analysis_module.__file__).parents[1] / name).read_bytes())
        for name in ('images/image_validation.py', 'images/image_metrics.py')})
    assert b['profiles']['classification']['paired_score_diagnostics']['leaderboard']['rbo']['p'] == .8
    assert (tmp_path / 'image-plan.json').read_bytes() == plan_bytes
    assert (tmp_path / 'image-results.json').read_bytes() == records_bytes
    with pytest.raises(ValueError, match='Unknown analysis'):
        generation_report(tmp_path, bootstrap=2, analysis={'typo': .8})
