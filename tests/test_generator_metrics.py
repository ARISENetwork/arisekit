import itertools
import math

import pytest

from arisekit.generation.generator_iteration import compare_model_profiles, kendall_tau_b
from arisekit.generation.generator_metrics import profile_diagnostics, rank_biased_overlap_a, somers_d, spearman_rho


def test_tied_rank_correlations_match_independent_pair_and_average_rank_examples():
    reference, candidate = [1, 1, 2], [1, 2, 3]
    assert spearman_rho(reference, candidate) == pytest.approx(math.sqrt(.75))
    assert somers_d(reference, candidate) == 1
    assert somers_d(candidate, reference) == pytest.approx(2 / 3)
    assert somers_d([1, 2, 3], [1, 1, 1]) == 0
    assert somers_d([1, 1, 1], [1, 2, 3]) is None
    rank = profile_diagnostics(reference, candidate)['rank']
    assert rank['pair_counts']['reference_only_ties'] == 1
    assert rank['net_pair_probability'] == pytest.approx(2 / 3)
    assert kendall_tau_b(reference, candidate) != rank['net_pair_probability']


def test_top_swap_has_same_tau_but_lower_rbo_than_bottom_swap():
    reference = [4, 3, 2, 1]
    top_swap, bottom_swap = [3, 4, 2, 1], [4, 3, 1, 2]
    assert kendall_tau_b(reference, top_swap) == kendall_tau_b(reference, bottom_swap)
    assert rank_biased_overlap_a(reference, top_swap, persistence=.5)['score'] == pytest.approx(.5)
    assert rank_biased_overlap_a(reference, bottom_swap, persistence=.5)['score'] == pytest.approx(23 / 24)


def test_rbo_ties_match_exhaustive_independent_permutations_without_id_tiebreaks():
    reference, candidate = [3, 3, 1], [1, 3, 3]
    def possible_orders(values):
        return [order for order in itertools.permutations(range(3))
                if all(values[order[i]] >= values[order[i + 1]] for i in range(2))]
    expected = []
    for a, b in itertools.product(possible_orders(reference), possible_orders(candidate)):
        agreement = [len(set(a[:d]) & set(b[:d])) / d for d in range(1, 4)]
        expected.append(.5 * sum(v * .5 ** i for i, v in enumerate(agreement)) + .5 ** 3)
    observed = rank_biased_overlap_a(reference, candidate, persistence=.5)
    assert observed['score'] == pytest.approx(sum(expected) / len(expected))
    assert rank_biased_overlap_a([3, 1, 3], [3, 3, 1], persistence=.5)['score'] == observed['score']


def test_rbo_exposes_tail_and_uncertainty_of_identical_ties():
    value = profile_diagnostics([1, 1, 1], [1, 1, 1], rbo_persistence=.5)['top_weighted']['rbo']
    assert value['score'] == pytest.approx(7 / 12)
    assert value['reference_self'] == value['candidate_self'] == value['score']
    reverse = rank_biased_overlap_a([4, 3, 2, 1], [1, 2, 3, 4], persistence=.9)
    assert reverse['tail_weight'] == pytest.approx(.9 ** 4)
    assert reverse['score'] >= reverse['tail_weight']
    assert reverse['prefix_weight'] + reverse['tail_weight'] == 1


def test_value_agreement_detects_constant_bias_despite_perfect_ranking():
    reference, candidate = [1, 2, 3], [2, 3, 4]
    value = profile_diagnostics(reference, candidate, agreement_tolerance=.5, tdi_probability=.9)['values']
    assert spearman_rho(reference, candidate) == 1
    assert value['lins_ccc'] == pytest.approx(4 / 7)
    assert value['icc_a1'] == pytest.approx(2 / 3)
    assert value['mean_bias'] == 1
    assert value['root_mean_squared_difference'] == 1
    assert value['coverage_probability']['estimate'] == 0
    assert value['total_deviation_index']['estimate'] == 1


def test_perfect_nonconstant_agreement_and_negative_icc_are_preserved():
    assert profile_diagnostics([1, 2, 3], [1, 2, 3])['values']['icc_a1'] == 1
    assert profile_diagnostics([1, 2, 3], [1, 2, 3])['values']['lins_ccc'] == 1
    value = profile_diagnostics([1, 2, 3], [3, 2, 1])['values']
    assert value['lins_ccc'] == -1
    assert value['icc_a1'] < 0


@pytest.mark.parametrize('values', [[], [1], [.1, .1, .1]])
def test_undefined_estimates_do_not_become_perfect_agreement(values):
    value = profile_diagnostics(values, values)
    assert value['rank']['spearman_rho'] is None
    assert value['rank']['somers_d_candidate_given_reference'] is None
    assert value['values']['lins_ccc'] is None
    assert value['values']['icc_a1'] is None


def test_no_implicit_top_weighting_or_acceptable_discrepancy():
    value = profile_diagnostics([1, 2], [1, 2])
    assert value['top_weighted'] == {'rbo': None, 'top_k': None}
    assert value['values']['coverage_probability']['estimate'] is None
    assert value['values']['total_deviation_index']['estimate'] is None


def test_top_k_includes_entire_boundary_ties_and_reports_actual_set_sizes():
    value = profile_diagnostics([3, 3, 1], [3, 1, 3], top_k=1)['top_weighted']['top_k']
    assert value['reference_count'] == value['candidate_count'] == 2
    assert value['intersection_count'] == 1
    assert value['union_count'] == 3
    assert value['jaccard'] == pytest.approx(1 / 3)


def test_coverage_and_tdi_use_models_and_empirical_quantiles_not_item_counts():
    value = profile_diagnostics([0, 0, 0, 0], [0, .25, .5, 1], agreement_tolerance=.25, tdi_probability=.6)
    assert value['n_models'] == 4
    assert value['values']['coverage_probability']['estimate'] == .5
    assert value['values']['total_deviation_index']['estimate'] == .5


@pytest.mark.parametrize('kwargs', [dict(rbo_persistence=1), dict(rbo_persistence=0),
    dict(rbo_persistence=float('nan')), dict(top_k=True), dict(top_k=3),
    dict(agreement_tolerance=-1), dict(agreement_tolerance=float('inf')), dict(tdi_probability=0)])
def test_invalid_analysis_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        profile_diagnostics([1, 2], [1, 2], **kwargs)


@pytest.mark.parametrize('a,b', [([1], [1, 2]), ([float('nan')], [1]), ([True], [1])])
def test_invalid_profiles_are_rejected(a, b):
    with pytest.raises(ValueError):
        profile_diagnostics(a, b)


def test_new_diagnostics_keep_measurement_and_operational_error_denominators_separate():
    rows = [dict(source=s, item='item', model=m, trial=1, score=v)
            for s in ('og', 'generated') for m, v in (('a', 1), ('b', .5))]
    rows[-1].update(score=None, error='provider error')
    result = compare_model_profiles(rows, models=['a', 'b'], items=['item'], trials=[1], reference='og', candidate='generated',
        rbo_persistence=.5, top_k=1, agreement_tolerance=.1, tdi_probability=.9)
    assert result['measurement']['additional_diagnostics']['n_models'] == 0
    assert result['measurement']['additional_diagnostics']['values']['lins_ccc'] is None
    assert result['operational']['additional_diagnostics']['n_models'] == 2
    assert result['operational']['additional_diagnostics']['values']['mean_bias'] == -.25
