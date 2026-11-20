import json

import pytest

from arisekit.generation.generator_iteration import compare_model_profiles, kendall_tau_b, run_generator_loop


class Callbacks:
    def __init__(self):
        self.calls = []
        self.interrupt = False

    def generate(self, context):
        self.calls.append(('generate', context['cycle']))
        return {'fresh_seed': context['specification']['seed'], 'strategy': context['strategy']}

    def evaluate(self, context):
        self.calls.append(('evaluate', context['cycle']))
        if self.interrupt:
            self.interrupt = False
            raise RuntimeError('interrupted evaluation')
        return {'lost_priority': 'preserve stat' not in context['strategy']}

    def diagnose(self, context):
        return {'generator_failure': 'priority omission' if context['evaluated']['lost_priority'] else None}

    def improve(self, context):
        return {'strategy': ['preserve stat']}


def run(root, callbacks, **changes):
    plan = {'mode': 'development', 'cycles': [{'seed': 1}, {'seed': 2}], 'initial_strategy': [], **changes}
    return run_generator_loop(plan, output_dir=root, generate=callbacks.generate,
        evaluate=callbacks.evaluate, diagnose=callbacks.diagnose, improve=callbacks.improve)


def test_diagnosis_changes_generator_strategy_on_fresh_cycle_and_resume_is_cached(tmp_path):
    callbacks = Callbacks()
    result = run(tmp_path, callbacks)
    assert result['cycles'][0]['diagnosis']['generator_failure'] == 'priority omission'
    assert result['cycles'][1]['generated'] == {'fresh_seed': 2, 'strategy': ['preserve stat']}
    assert result['cycles'][1]['diagnosis']['generator_failure'] is None
    assert run(tmp_path, callbacks) == result
    assert callbacks.calls == [('generate', 1), ('evaluate', 1), ('generate', 2), ('evaluate', 2)]


def test_interruption_preserves_completed_generation_before_evaluation(tmp_path):
    callbacks = Callbacks()
    callbacks.interrupt = True
    with pytest.raises(RuntimeError):
        run(tmp_path, callbacks)
    run(tmp_path, callbacks)
    assert callbacks.calls.count(('generate', 1)) == 1
    assert callbacks.calls.count(('evaluate', 1)) == 2


def test_changed_plan_or_tampered_diagnosis_cannot_reuse_completed_loop(tmp_path):
    callbacks = Callbacks()
    run(tmp_path, callbacks)
    with pytest.raises(ValueError, match='frozen'):
        run(tmp_path, callbacks, initial_strategy=['new'])
    path = tmp_path / 'cycle-1/diagnosis.json'
    data = json.loads(path.read_text())
    data['output']['generator_failure'] = 'hidden mutation'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Retained generator stage'):
        run(tmp_path, callbacks)


def test_final_holdout_cannot_be_used_as_optimization_material(tmp_path):
    with pytest.raises(ValueError, match='development material'):
        run(tmp_path, Callbacks(), mode='held-out')


def test_critic_cannot_change_budget_or_other_frozen_fields(tmp_path):
    class BadRevision(Callbacks):
        def improve(self, context):
            return {'strategy':['change'], 'max_cost':1000}
    with pytest.raises(ValueError, match='only a list of strategy'):
        run(tmp_path, BadRevision())


def test_tau_retains_ties_and_undefined_profiles():
    assert kendall_tau_b([1, 2, 3], [1, 2, 3]) == 1
    assert kendall_tau_b([1, 2, 3], [3, 2, 1]) == -1
    assert kendall_tau_b([1, 1, 1], [1, 2, 3]) is None
    assert kendall_tau_b([1, 1, 2], [1, 2, 3]) == pytest.approx(.8164965809)


def test_provider_error_is_missing_measurement_and_separate_operational_failure():
    rows = [{'source': source, 'item': item, 'model': model, 'trial': 1,
             'score': value, 'error': None}
        for item in ('a', 'b') for source in ('original', 'generated')
        for model, value in [('strong', 1), ('weak', 0)]]
    next(r for r in rows if r['source']=='generated' and r['item']=='a' and r['model']=='strong').update(score=None, error='upstream 429')
    result = compare_model_profiles(rows, models=['strong', 'weak'], items=['a', 'b'],
        trials=[1], reference='original', candidate='generated')
    assert result['measurement']['units'] == 1
    assert result['measurement']['score_shifts'] == [0, 0]
    assert result['operational']['score_shifts'] == [-.5, 0]
    assert result['unavailable_measurements'][0]['error'] == 'upstream 429'


def test_tau_cannot_hide_a_large_calibration_shift():
    rows = [{'source': source, 'item': 'a', 'model': model, 'trial': 1, 'score': score + shift}
        for source, shift in [('original', 0), ('generated', .4)]
        for model, score in [('strong', .5), ('weak', .1)]]
    result = compare_model_profiles(rows, models=['strong', 'weak'], items=['a'], trials=[1],
        reference='original', candidate='generated')
    assert result['measurement']['kendall_tau_b'] == 1
    assert result['measurement']['mean_absolute_score_shift'] == pytest.approx(.4)


def test_unobserved_or_duplicate_cells_are_explicit():
    result = compare_model_profiles([], models=['a', 'b'], items=['item'], trials=[1],
        reference='original', candidate='generated')
    assert result['measurement']['kendall_tau_b'] is None
    assert len(result['unavailable_measurements']) == 4
    row = {'source':'original', 'item':'item', 'model':'a', 'trial':1, 'score':1}
    with pytest.raises(ValueError, match='Duplicate'):
        compare_model_profiles([row, row], models=['a'], items=['item'], trials=[1], reference='original', candidate='generated')
