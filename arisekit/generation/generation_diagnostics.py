"""Descriptive model comparisons without changing references or selecting cases."""
from itertools import combinations
import math


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _ranks(values):
    return [1 + sum(other < value for other in values) + (values.count(value)-1)/2 for value in values]


def _correlation(x, y):
    mx, my = sum(x)/len(x), sum(y)/len(y)
    denominator = sum((v-mx)**2 for v in x) * sum((v-my)**2 for v in y)
    return sum((a-mx)*(b-my) for a, b in zip(x, y))/math.sqrt(denominator) if denominator else None


def _arm(value, expected):
    if value is None:
        return {'expected': expected, 'observed': 0, 'missing': expected, 'mean': None,
                'assigned_mean_bounds': [0., 1.] if expected else None, 'status': 'not_evaluated'}
    result = {key: value.get(key, 0) for key in ['expected', 'observed', 'missing', 'errors', 'invalid', 'truncated_solver_outputs', 'missing_judgments']}
    result['mean'] = value.get('mean') if _finite(value.get('mean')) else None
    complete = (result['mean'] is not None and result['expected'] > 0 and result['observed'] == result['expected']
                and not any(result[k] for k in ['missing', 'errors', 'invalid', 'truncated_solver_outputs', 'missing_judgments']))
    result['status'] = 'complete' if complete else 'incomplete'
    result['assigned_mean_bounds'] = [result['mean']]*2 if complete else [0., 1.] if result['expected'] else None
    return result


def comparison_diagnosis(rows, *, models=None, case_counts=None):
    """Compare matched model means; preserve unobserved assignments explicitly."""
    indexed = {row['model']: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError('Duplicate model identities cannot define a comparison')
    models = list(models if models is not None else indexed)
    if len(set(models)) != len(models) or not set(indexed) <= set(models):
        raise ValueError('Comparison must use the frozen model panel')
    counts = case_counts or {}
    per_model = []
    for model in models:
        row = indexed.get(model, {})
        arms = {key: _arm(row.get(key), counts.get(key)) for key in ['original', 'generated']}
        a, b = arms['original']['assigned_mean_bounds'], arms['generated']['assigned_mean_bounds']
        per_model.append({'model': model, **arms, 'signed_bias_bounds': [b[0]-a[1], b[1]-a[0]] if a and b else None})
    complete = [r for r in per_model if all(r[key]['status'] == 'complete' for key in ['original', 'generated'])]
    x, y = [r['original']['mean'] for r in complete], [r['generated']['mean'] for r in complete]
    n = len(x);values = {'models_observed': n, 'models_assigned': len(models), 'signed_bias': None,
        'mean_absolute_error': None, 'lin_ccc': None, 'spearman_rho': None, 'kendall_tau_b': None}
    if n:
        values.update(signed_bias=sum(b-a for a, b in zip(x, y))/n, mean_absolute_error=sum(abs(b-a) for a, b in zip(x, y))/n)
    if n >= 2:
        mx, my = sum(x)/n, sum(y)/n
        denominator = sum((a-mx)**2+(b-my)**2 for a, b in zip(x, y))/n + (mx-my)**2
        values['lin_ccc'] = 2*sum((a-mx)*(b-my) for a, b in zip(x, y))/n/denominator if denominator else None
        values['spearman_rho'] = _correlation(_ranks(x), _ranks(y))
        concordant = discordant = untied_x = untied_y = 0
        for i, j in combinations(range(n), 2):
            a, b = x[i]-x[j], y[i]-y[j]
            untied_x += a != 0;untied_y += b != 0
            concordant += a*b > 0;discordant += a*b < 0
        values['kendall_tau_b'] = (concordant-discordant)/math.sqrt(untied_x*untied_y) if untied_x*untied_y else None
    gaps = []
    for a, b in combinations(per_model, 2):
        row = {'first': a['model'], 'second': b['model']}
        for arm in ['original', 'generated']:
            left, right = a[arm]['assigned_mean_bounds'], b[arm]['assigned_mean_bounds']
            row[arm+'_gap_bounds'] = [left[0]-right[1], left[1]-right[0]] if left and right else None
        gaps.append(row)
    return {'schema': 'arisekit.generation-diagnosis.v1', 'models': per_model, 'complete_subpanel': values,
        'pairwise_model_gaps': gaps, 'clinical_items_paired': False, 'comparison_units': 'matched_model_means',
        'missing_scores_imputed': False, 'bounds_are_confidence_intervals': False,
        'incomplete_arm_bounds': 'Conservative 0–1 bounds; no unavailable primary mean is invented',
        'generation_or_case_selection_gate': False, 'automatic_case_reference_or_weight_changes': False,
        'expert_outcomes': 0}
