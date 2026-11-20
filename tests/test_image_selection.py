import pytest

from arisekit.images.image_selection import select_comparison_preserving_revision


def diagnosis(original, generated):
    rows = [{'model': name, 'forms': {style: {'original': original[i], 'generated': generated[i]}
                                  for style in ('direct', 'selection')}} for i, name in enumerate(('a', 'b', 'c'))]
    gaps = [abs(a - b) for a, b in zip(original, generated)]
    return {'parent_plan_sha256': str(generated), 'wording': {'copied_original': 0},
        'profiles': {'classification': {'models': [{'model': name,
            'original': {'correct': round(original[i] * 1000), 'assigned': 1000},
            'generated': {'correct': round(generated[i] * 1000), 'assigned': 1000}}
            for i, name in enumerate(('a', 'b', 'c'))], 'concordance': {'discordant': 0}, 'calibration': {'models': rows,
            'mean_absolute_score_error': sum(gaps) / 3, 'maximum_absolute_score_error': max(gaps)}}}}


def setup_panels(monkeypatch, panels):
    import arisekit.images.image_selection as module
    monkeypatch.setattr(module, 'select_development_revision', lambda roots: {'selected': {'run': 'calibration-only'}})
    monkeypatch.setattr(module, 'development_diagnosis', lambda root: panels[root])
    monkeypatch.setattr(module, '_frozen_plan', lambda root: {'runtime_sha256': 'fixture-runtime'})
    monkeypatch.setattr(module, '_wording_requirements', lambda root, values: {
        'exact_original_matches': values['wording']['copied_original'], 'distinct_forms_for_every_source_task': True,
        'prefix_only_original_matches':values['wording'].get('prefix_only_original_copies',0)})


def test_lower_calibration_error_cannot_hide_reversed_stable_pair(monkeypatch):
    panels = {'preserving': diagnosis([.8, .7, .5], [.9, .8, .6]),
              'reversing': diagnosis([.8, .7, .5], [.7, .8, .5])}
    setup_panels(monkeypatch, panels)
    result = select_comparison_preserving_revision(list(panels))
    assert result['selected']['run'] == 'preserving'
    assert result['candidates'][0]['selection_key'][1] > result['candidates'][1]['selection_key'][1]
    assert len(result['original_stable_pairs']['classification']) == 3


def test_source_instability_is_not_declared_a_stable_comparison(monkeypatch):
    panels = {'first': diagnosis([.8, .7, .5], [.8, .7, .5]),
              'second': diagnosis([.7, .8, .5], [.7, .8, .5])}
    setup_panels(monkeypatch, panels)
    pairs = select_comparison_preserving_revision(list(panels))['original_stable_pairs']['classification']
    assert len(pairs) == 2
    assert all({pair['left'], pair['right']} != {'a', 'b'} for pair in pairs)


def test_collapsing_original_comparisons_is_reported(monkeypatch):
    panels = {'collapse': diagnosis([.8, .7, .5], [.7, .7, .5])}
    setup_panels(monkeypatch, panels)
    result = select_comparison_preserving_revision(list(panels))
    assert result['selected']['selection_key'][0] == 1
    assert sum(row['outcome'] == 'collapsed' for row in result['selected']['stable_pair_outcomes']) == 1


def test_reusing_original_wording_cannot_win_by_perfect_calibration(monkeypatch):
    panels = {'novel': diagnosis([.8, .7, .5], [.9, .8, .6]),
              'original-copy': diagnosis([.8, .7, .5], [.8, .7, .5])}
    panels['original-copy']['wording']['copied_original'] = 1
    setup_panels(monkeypatch, panels)
    result = select_comparison_preserving_revision(list(panels))
    assert result['selected']['run'] == 'novel'
    assert not result['candidates'][1]['eligible_novel_forms']


def test_all_original_copies_do_not_produce_a_favorable_selection(monkeypatch):
    panels = {'copy': diagnosis([.8, .7, .5], [.8, .7, .5])}
    panels['copy']['wording']['copied_original'] = 1
    setup_panels(monkeypatch, panels)
    with pytest.raises(ValueError, match='distinct novel wordings'):
        select_comparison_preserving_revision(list(panels))
    result = select_comparison_preserving_revision(list(panels), allow_no_selection=True)
    assert result['selected'] is None and len(result['candidates']) == 1
    assert result['calibration_first_selection']['run'] == 'calibration-only'


def test_real_styled_run_supplies_novel_forms_for_selection(tmp_path):
    from test_image_iteration import styled_run
    styled_run(tmp_path)
    result = select_comparison_preserving_revision([tmp_path])
    assert result['selected']['eligible_novel_forms']
    assert result['selected']['wording_requirements']['distinct_forms_for_every_source_task']


def test_equal_pooled_counts_are_collapsed_despite_rounded_form_differences(monkeypatch):
    panel = diagnosis([.9, .8, .5], [17 / 24, 17 / 24, .5])
    forms = panel['profiles']['classification']['calibration']['models']
    forms[0]['forms']['direct']['generated'] = 8 / 12
    forms[0]['forms']['selection']['generated'] = 9 / 12
    forms[1]['forms']['direct']['generated'] = 7 / 12
    forms[1]['forms']['selection']['generated'] = 10 / 12
    setup_panels(monkeypatch, {'equal': panel})
    result = select_comparison_preserving_revision(['equal'])
    pair = next(row for row in result['selected']['stable_pair_outcomes'] if row['left'] == 'a' and row['right'] == 'b')
    assert pair['outcome'] == 'collapsed'


def test_original_informed_prefix_copy_cannot_win_on_calibration(monkeypatch):
    panels={'novel':diagnosis([.8,.7,.5],[.9,.8,.6]),'prefix-copy':diagnosis([.8,.7,.5],[.8,.7,.5])}
    for panel in panels.values():panel['wording']['original_question_access']=True
    panels['prefix-copy']['wording']['prefix_only_original_copies']=1
    setup_panels(monkeypatch,panels)
    result=select_comparison_preserving_revision(list(panels))
    assert result['selected']['run']=='novel' and not result['candidates'][1]['eligible_novel_forms']
