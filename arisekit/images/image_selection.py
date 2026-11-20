"""Select generator criteria while protecting reproducible original comparisons."""

from itertools import combinations
from pathlib import Path

from arisekit.images.image_iteration import _calibration_key, development_diagnosis, select_development_revision
from arisekit.images.image_generation import _frozen_plan
from arisekit.images.image_validation import generation_report
from arisekit.images.imaging import digest


def _wording_requirements(root, diagnosis):
    variation = generation_report(root)['originality']['per_source_question_variation']
    return {'exact_original_matches': diagnosis['wording']['copied_original'],
        'prefix_only_original_matches': diagnosis['wording'].get('prefix_only_original_copies', 0),
        'distinct_forms_for_every_source_task': all(row['assigned_forms'] == row['distinct_wordings'] for row in variation)}


def select_comparison_preserving_revision(roots, *, allow_no_selection=False):
    """Use original repeats to define stable pairs before comparing candidates."""
    legacy = select_development_revision(roots)
    diagnoses = [development_diagnosis(root) for root in roots]
    references = {}
    for profile in diagnoses[0]['profiles']:
        panels = [diagnosis['profiles'][profile]['calibration']['models'] for diagnosis in diagnoses]
        names = [row['model'] for row in panels[0]]
        stable = []
        for left, right in combinations(names, 2):
            deltas = []
            for panel in panels:
                indexed = {row['model']: row for row in panel}
                for style in indexed[left]['forms']:
                    deltas.append(indexed[left]['forms'][style]['original'] - indexed[right]['forms'][style]['original'])
            direction = 1 if all(value > 0 for value in deltas) else -1 if all(value < 0 for value in deltas) else 0
            if direction:
                stable.append({'left': left, 'right': right, 'direction': direction, 'original_repeat_deltas': deltas})
        references[profile] = stable
    candidates = []
    for root, diagnosis in zip(roots, diagnoses):
        wording = _wording_requirements(root, diagnosis)
        outcomes = []
        for profile, pairs in references.items():
            indexed = {row['model']: row for row in diagnosis['profiles'][profile]['calibration']['models']}
            totals = {row['model']: row['generated'] for row in diagnosis['profiles'][profile]['models']}
            for pair in pairs:
                left, right = indexed[pair['left']], indexed[pair['right']]
                differences = [left['forms'][style]['generated'] - right['forms'][style]['generated'] for style in left['forms']]
                a, b = totals[pair['left']], totals[pair['right']]
                mean = a['correct'] * b['assigned'] - b['correct'] * a['assigned']
                outcome = 'preserved' if mean * pair['direction'] > 0 else 'reversed' if mean * pair['direction'] < 0 else 'collapsed'
                outcomes.append({'profile': profile, 'left': pair['left'], 'right': pair['right'], 'outcome': outcome,
                    'generated_form_deltas': differences, 'all_forms_preserve': all(value * pair['direction'] > 0 for value in differences)})
        calibration = _calibration_key(diagnosis['profiles'])
        key = [sum(row['outcome'] != 'preserved' for row in outcomes),
            float(calibration[0]), float(calibration[1])]
        candidates.append({'run': str(root), 'plan_sha256': diagnosis['parent_plan_sha256'],
            'generation_runtime_sha256': _frozen_plan(Path(root))['runtime_sha256'],
            'selection_key': key, 'stable_pair_outcomes': outcomes, 'wording': diagnosis['wording'],
            'wording_requirements': wording,
            'eligible_novel_forms': wording['exact_original_matches'] == 0 and wording['distinct_forms_for_every_source_task'] and
                (not diagnosis['wording'].get('original_question_access') or wording['prefix_only_original_matches'] == 0)})
    eligible = [index for index, row in enumerate(candidates) if row['eligible_novel_forms']]
    if not eligible and not allow_no_selection:
        raise ValueError('No development candidate supplies distinct novel wordings for every requested form')
    selected = min(eligible, key=lambda index: (*candidates[index]['selection_key'], index)) if eligible else None
    return {'selected': candidates[selected] if selected is not None else None, 'candidates': candidates, 'original_stable_pairs': references,
        'calibration_first_selection': legacy['selected'],
        'rule': 'Fewest lost stable-original comparisons, then mean absolute score error, then maximum error; first candidate breaks ties.',
        'wording_requirement': 'Requested forms must be distinct per source task with no exact original matches. Original-informed runs must also avoid prefix-only original copies. This is not a conceptual novelty claim.',
        'stable_pair_definition': 'Same strict direction in every original repeat from every development candidate; generated answers do not define these pairs.',
        'selection_source_sha256': digest(Path(__file__).read_bytes())}
