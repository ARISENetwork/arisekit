import itertools
import math
import random
import warnings

import pytest

from arisekit.images.image_metrics import analysis_options, paired_score_diagnostics


def test_uniform_difficulty_shift_preserves_ranks_but_penalizes_absolute_agreement():
    result = paired_score_diagnostics([1, .5], [.75, .25])
    assert result['rank']['spearman_rho'] == pytest.approx(1)
    assert result['rank']['somers_d_generated_given_original'] == 1
    assert result['leaderboard']['rbo']['rbo_a_ext'] == pytest.approx(1)
    icc = result['values']['icc_absolute_single']
    assert icc['value'] == pytest.approx(.8)
    assert icc['form'] == 'ICC(A,1)'
    assert icc['definition'] == 'absolute agreement'
    assert result['values']['empirical_tdi']['value_pp'] == 25
    assert result['values']['coverage_probability']['value'] is None
    assert result['values']['deming']['slope'] is None


def test_top_swap_hurts_more_than_bottom_swap():
    x = [.9, .8, .7, .6, .5, .4]
    top, bottom = x.copy(), x.copy()
    top[0], top[1] = top[1], top[0]
    bottom[-1], bottom[-2] = bottom[-2], bottom[-1]
    a, b = [paired_score_diagnostics(x, y) for y in (top, bottom)]
    assert a['rank']['weighted_kendall_tau'] < b['rank']['weighted_kendall_tau']
    assert a['leaderboard']['rbo']['rbo_a_ext'] < b['leaderboard']['rbo']['rbo_a_ext']
    assert a['leaderboard']['top_k'][0]['jaccard'] == 0
    assert b['leaderboard']['top_k'][0]['jaccard'] == 1


def test_somers_direction_counts_only_untied_original_pairs():
    x, y = [0, .5, 1], [0, .5, .5]
    forward, backward = [paired_score_diagnostics(a, b)['rank'] for a, b in ((x, y), (y, x))]
    assert forward['somers_d_generated_given_original'] == 2 / 3
    assert forward['somers_denominator_original_untied_pairs'] == 3
    assert backward['somers_d_generated_given_original'] == 1
    assert backward['somers_denominator_original_untied_pairs'] == 2


def test_reference_rank_statistics_match_scipy_on_ties():
    stats = pytest.importorskip('scipy.stats')
    rng = random.Random(20261024)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for _ in range(80):
            x, y = [[rng.randrange(4) / 4 for _ in range(6)] for _ in range(2)]
            result = paired_score_diagnostics(x, y)['rank']
            ranks = [sum(v > value for v in x) for value in x]
            for key, expected in [
                ('spearman_rho', stats.spearmanr(x, y).statistic),
                ('somers_d_generated_given_original', stats.somersd(x, y).statistic),
                ('weighted_kendall_tau', stats.weightedtau(x, y, rank=False, weigher=lambda i: 1 / (ranks[i] + 1)).statistic),
            ]:
                assert result[key] == pytest.approx(expected) if not math.isnan(expected) else result[key] is None


def _permutations(scores):
    groups = [[i for i, v in enumerate(scores) if v == value] for value in sorted(set(scores), reverse=True)]
    return [sum((list(group) for group in ordering), [])
            for ordering in itertools.product(*(itertools.permutations(group) for group in groups))]


@pytest.mark.parametrize('x,y', [([1, 1, 0], [1, 0, 0]), ([1, 1, 1], [1, 1, 1]), ([1, .5, 0], [0, .5, 1])])
def test_rbo_a_matches_exhaustive_independent_tie_permutations(x, y):
    p, n = .8, len(x)
    scores = []
    for a, b in itertools.product(_permutations(x), _permutations(y)):
        scores.append((1 - p) * sum(p ** (d - 1) * len(set(a[:d]) & set(b[:d])) / d
                                   for d in range(1, n + 1)) + p ** n)
    actual = paired_score_diagnostics(x, y, settings={'rbo_p': p})['leaderboard']['rbo']
    assert actual['rbo_a_ext'] == pytest.approx(sum(scores) / len(scores))
    assert actual['tail_mass'] == pytest.approx(p ** n)
    assert actual['prefix_weighted_sum'] + actual['tail_mass'] == pytest.approx(actual['rbo_a_ext'])


def test_tie_boundary_sets_and_metrics_are_invariant_to_model_row_order():
    x, y = [1, 1, .5, 0], [1, .5, .5, 0]
    expected = paired_score_diagnostics(x, y)
    top = expected['leaderboard']['top_k'][0]
    assert (top['original_set_size'], top['generated_set_size'], top['jaccard']) == (2, 1, .5)
    for order in itertools.permutations(range(4)):
        actual = paired_score_diagnostics([x[i] for i in order], [y[i] for i in order])
        assert actual['rank'] == expected['rank']
        assert actual['leaderboard'] == expected['leaderboard']
        assert actual['values']['icc_absolute_single']['value'] == pytest.approx(expected['values']['icc_absolute_single']['value'])


def test_all_tied_panels_do_not_invent_an_order_or_an_icc():
    result = paired_score_diagnostics([.5] * 4, [.5] * 4)
    assert result['rank']['spearman_rho'] is None
    assert result['rank']['somers_d_generated_given_original'] is None
    assert result['rank']['weighted_kendall_tau'] is None
    assert result['rank']['reference_order_status'] == 'all-original-scores-tied'
    assert result['values']['icc_absolute_single']['value'] is None
    assert result['leaderboard']['rbo']['rbo_a_ext'] < 1
    assert result['leaderboard']['top_k'][0]['original_set_size'] == 4


def test_negative_icc_is_not_clipped():
    result = paired_score_diagnostics([0, .5, 1], [1, .5, 0])
    assert result['values']['icc_absolute_single']['value'] == pytest.approx(-3)


def test_empirical_coverage_and_inverse_cdf_tdi_use_models_and_pp():
    result = paired_score_diagnostics([0] * 4, [0, .05, .1, .5],
        settings={'coverage_tolerance_pp': 10, 'tdi_probability': .75})['values']
    assert result['coverage_probability'] == {'status': 'descriptive-estimate', 'tolerance_pp': 10,
        'boundary_roundoff_tolerance_pp': 1e-10, 'within': 3, 'models': 4, 'value': .75}
    assert result['empirical_tdi']['value_pp'] == 10
    assert result['empirical_tdi']['observed_coverage'] == .75
    assert paired_score_diagnostics([.6, .7], [.7, .8],
        settings={'coverage_tolerance_pp': 10})['values']['coverage_probability']['within'] == 2


def test_deming_requires_explicit_variance_ratio_and_recovers_scale_and_offset():
    x, y = [.1, .2, .3, .4], [.3, .5, .7, .9]
    result = paired_score_diagnostics(x, y, settings={'deming_error_ratio': 4})['values']['deming']
    assert result['slope'] == pytest.approx(2)
    assert result['intercept'] == pytest.approx(.1)
    assert result['error_variance_ratio_generated_over_original'] == 4
    zero = paired_score_diagnostics([.5, .5], [.2, .8], settings={'deming_error_ratio': 1})
    assert zero['values']['deming']['status'] == 'undefined-zero-covariance'


@pytest.mark.parametrize('settings', [[], {'unexpected': 1}, {'rbo_p': 1}, {'rbo_p': 0},
    {'rbo_p': float('nan')}, {'tdi_probability': 0}, {'coverage_tolerance_pp': -1},
    {'coverage_tolerance_pp': 101}, {'deming_error_ratio': 0}, {'deming_error_ratio': True}])
def test_invalid_analysis_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        analysis_options(settings)


@pytest.mark.parametrize('x,y', [([1], [1]), ([1, 2], [1, 2]), ([0, .5], [0, float('nan')]), ([0, 1], [0])])
def test_bad_pairing_and_units_are_rejected(x, y):
    with pytest.raises(ValueError):
        paired_score_diagnostics(x, y)


def test_zero_margin_is_exact_and_tdi_decimal_probability_has_no_index_roundoff():
    a = paired_score_diagnostics([.5, .5], [.5, .5 + 1e-14], settings={'coverage_tolerance_pp': 0})
    assert a['values']['coverage_probability']['within'] == 1
    b = paired_score_diagnostics([0] * 50, [i / 100 for i in range(50)], settings={'tdi_probability': .14})
    assert b['values']['empirical_tdi']['value_pp'] == 6


def test_deming_extreme_declared_ratio_avoids_intermediate_overflow():
    result = paired_score_diagnostics([.1, .2, .3], [.2, .4, .6],
        settings={'deming_error_ratio': 1e308})['values']['deming']
    assert result['slope'] == pytest.approx(2)
    assert math.isfinite(result['intercept'])
