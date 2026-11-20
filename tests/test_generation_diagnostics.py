from arisekit.generation.generation_diagnostics import comparison_diagnosis


def arm(mean, n=20, **changes):
    return {'mean': mean, 'expected': n, 'observed': n, 'missing': 0, 'errors': 0, **changes}


def test_same_order_with_easier_generated_scores_has_poor_value_agreement():
    rows = [{'model': str(i), 'original': arm(a), 'generated': arm(a+.4)} for i, a in enumerate([.2, .3, .4])]
    d = comparison_diagnosis(rows)['complete_subpanel']
    assert abs(d['signed_bias']-.4) < 1e-12
    assert d['spearman_rho'] == 1
    assert d['lin_ccc'] < .1


def test_unavailable_model_and_failed_assignment_remain_in_denominators():
    rows = [{'model': 'a', 'original': arm(.4), 'generated': arm(None, observed=19, missing=1, truncated_solver_outputs=1)}]
    d = comparison_diagnosis(rows, models=['a', 'b'], case_counts={'original': 23, 'generated': 20})
    assert d['complete_subpanel']['models_assigned'] == 2
    assert d['complete_subpanel']['models_observed'] == 0
    assert d['models'][0]['generated']['missing'] == 1
    assert d['models'][1]['generated']['missing'] == 20
    assert d['models'][0]['generated']['mean'] is None
    assert d['models'][0]['generated']['assigned_mean_bounds'] == [0, 1]


def test_ties_are_not_broken_and_original_generated_cases_are_unpaired():
    rows = [{'model': str(i), 'original': arm(.5), 'generated': arm(.8)} for i in range(2)]
    d = comparison_diagnosis(rows)
    assert d['complete_subpanel']['spearman_rho'] is None
    assert d['complete_subpanel']['kendall_tau_b'] is None
    assert d['pairwise_model_gaps'][0]['original_gap_bounds'] == [0, 0]
    assert d['clinical_items_paired'] is False


def test_invalid_outcomes_cannot_enter_complete_model_agreement():
    rows = [{'model': 'a', 'original': arm(.4), 'generated': arm(.8, invalid=1)}]
    diagnosis = comparison_diagnosis(rows)
    assert diagnosis['complete_subpanel']['models_observed'] == 0
    assert diagnosis['models'][0]['generated']['status'] == 'incomplete'
    assert diagnosis['models'][0]['generated']['assigned_mean_bounds'] == [0, 1]
