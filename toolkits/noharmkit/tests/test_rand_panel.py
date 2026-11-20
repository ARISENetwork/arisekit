"""RAND-style panel regression tests use synthetic fixtures and no live providers."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, synthetic_table

from pipeline import backends
from pipeline.e2e import rand
from pipeline.e2e.rubric import OPTION_FIELDS, Rubric
from tools import noharm
from arisekit.common.hashing import json_sha256

PANEL = [{"backend": "codex", "model": name, "reasoning_effort": "medium"} for name in ["a", "b", "c"]]
CASE = {"presentation": "A synthetic task needs a plan.", "recommendations": "Perform synthetic checks."}


def reply(schema: dict[str, Any]) -> dict[str, Any]:
    def fill(node: dict[str, Any]) -> Any:
        if node['type'] == 'object':
            return {key: fill(value) for key, value in node['properties'].items()}
        if node['type'] == 'integer':
            return 8
        return 'moderate' if 'enum' in node else 'Synthetic reason or discussion.'
    return fill(schema)


def fake_provider(monkeypatch: pytest.MonkeyPatch, *, fail: str | None = None,
                  malformed: str | None = None) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def call(backend: str, model: str, system: str, prompt: str, **kwargs: Any) -> backends.CallResult:
        payload = json.loads(prompt.split('Input JSON:\n')[1])
        phase = f"round{payload['round']}" if 'round' in payload else 'moderation' if 'discussion' in payload else 'discussion'
        calls.append({'phase': phase, 'model': model, 'payload': payload, 'schema': kwargs['json_schema'], 'system': system})
        if phase == fail and model == 'a':
            raise backends.BackendError('Synthetic provider failure', raw='retained failure')
        out = reply(kwargs['json_schema'])
        if 'options' in out:
            for options in out['options'].values():
                for option in options.values():
                    option['score'] = {'a': 7, 'b': 8, 'c': 9}[model]
        if malformed and phase == 'round1' and model == 'a':
            if malformed == 'boolean':
                next(iter(next(iter(out['options'].values())).values()))['score'] = True
            elif malformed == 'float':
                next(iter(next(iter(out['options'].values())).values()))['score'] = 8.0
            elif malformed == 'missing':
                del next(iter(out['options'].values()))['R1']
            elif malformed == 'extra':
                out['options']['unknown'] = {}
            elif malformed == 'empty':
                out['usualCare']['reason'] = '  '
            elif malformed == 'harm':
                out['usualCare']['harm'] = 'mild'
        raw = json.dumps(out)
        if malformed == 'duplicate' and phase == 'round1' and model == 'a':
            raw = raw.replace('"score": 7', '"score": 7, "score": 8', 1)
        return backends.CallResult(raw, {'backend': backend, 'model': model, 'runtime_s': 0.0})

    monkeypatch.setattr(backends, 'call', call)
    return calls


def test_appropriateness() -> None:
    cases: list[tuple[list[int], dict[str, Any], dict[str, float]]] = [  # votes, exact fields, approximate fields
        ([1,1,1,2,3,3,6,6,6,6,8,8], {'disagreement': True}, {'p30': 2.3, 'p70': 6.0, 'ipras': 3.625}),
        ([1,1,2,2,3,3,3,3,7,7,7,8], {'disagreement': False}, {'p30': 2.3, 'p70': 5.8, 'ipras': 3.775}),
        ([3,4], {'median': 3.5, 'classification': 'uncertain', 'disagreement': False}, {}),
        ([6,7], {'median': 6.5, 'classification': 'uncertain', 'disagreement': False}, {}),
        ([8,8,8], {'median': 8, 'classification': 'appropriate', 'disagreement': False}, {}),
        ([1,2,3], {'median': 2, 'classification': 'inappropriate', 'disagreement': False}, {}),
        ([1,1,1,5,5,5,9,9,9], {'median': 5, 'classification': 'uncertain', 'disagreement': True}, {}),
        ([1,9,9], {'median': 9, 'classification': 'appropriate', 'disagreement': False}, {}),
    ]

    def run(case: tuple[list[int], dict[str, Any], dict[str, float]]) -> None:
        votes, exact, approx = case
        item = rand.appropriateness(votes)
        for key, value in exact.items():
            if isinstance(value, bool):
                assert item[key] is value
            else:
                assert item[key] == value
        for key, value in approx.items():
            assert item[key] == pytest.approx(value)
        reverse = rand.appropriateness(list(reversed(votes)))
        assert {k: v for k, v in item.items() if k != 'votes'} == {k: v for k, v in reverse.items() if k != 'votes'}

    each_case(cases, lambda c: str(c[0]), run)


def test_projection_blinds_grades_preserves_all_options_and_conditions() -> None:
    table = synthetic_table()
    table['decisions'][1]['activation'] = {'type': 'onlyIf', 'rows': ['D1.O1']}
    projected, row_map = Rubric(table).neutral_view(table["decisions"], OPTION_FIELDS)
    assert len(projected) == len(table['decisions'])
    assert sum(len(d['rows']) for d in projected) == sum(len(d['recommendations']) for d in table['decisions'])
    assert not {'score', 'harm', 'kind', 'relativeHarmOverride', 'alsoTakesCareOf'} & {
        key for d in projected for row in d['rows'] for key in row}
    assert projected[4]['rows'][0].get('parts') is not None or any('parts' in r for d in projected for r in d['rows'])
    assert all(set(row_map[d['id']].values()) == {r['id'] for r in d['recommendations']} for d in table['decisions'])
    assert 'ifRecommended' in next(d for d in projected if d['activation']['type'] == 'onlyIf')['activation']


def test_complete_two_round_panel_is_advisory_and_personalized(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_provider(monkeypatch)
    table = synthetic_table(); before = copy.deepcopy(table)
    record = rand.run_panel(CASE, table, PANEL, evidence='Supplied synthetic evidence.', save=lambda *_: None)
    assert record['status'] == 'pass' and record['authority'] == 'llm-provisional' and not record['applied']
    assert len(calls) == record['planned_calls'] == 10
    assert table == before
    first = [c for c in calls if c['phase'] == 'round1']
    assert all('feedback' not in c['payload'] and 'own_round1' not in c['payload'] for c in first)
    second = [c for c in calls if c['phase'] == 'round2']
    by_model = {member['model']: record['round1'][index]['output'] for index, member in enumerate(PANEL)}
    assert all(c['payload']['own_round1'] == by_model[c['model']] for c in second)
    assert all(c['payload']['moderator'] == record['moderation']['output'] for c in second)
    assert all(c['payload']['discussion'] == [r['output'] for r in record['discussion']] for c in second)
    assert all(c['payload']['evidence'] == 'Supplied synthetic evidence.' for c in calls)
    assert record['aggregate']['options']['D1']['D1.O1']['median'] == 8
    excluded = {d['id'] for d in table['decisions'] if d['id'] not in record['aggregate']['decisions']}
    assert excluded and excluded <= set(record['aggregate']['options'])
    assert all(r['provenance']['request_sha256'] for r in record['round1'] + record['discussion'] + record['round2'])
    assert record['case_sha256'] == json_sha256(CASE)
    assert record['evidence_sha256'] == hashlib.sha256(b'Supplied synthetic evidence.').hexdigest()


@pytest.mark.parametrize('phase,count', [('round1',3), ('discussion',6), ('moderation',7), ('round2',10)])
def test_failed_phase_stops_and_preserves_every_completed_receipt(monkeypatch: pytest.MonkeyPatch, phase: str, count: int) -> None:
    calls = fake_provider(monkeypatch, fail=phase)
    saved: dict[str, Any] = {}
    record = rand.run_panel(CASE, synthetic_table(), PANEL, save=lambda name, value: saved.update({name: value}))
    assert record['status'] == 'failed' and record['aggregate'] is None and record['errors']
    assert len(calls) == count and len(saved) == count + 1
    assert any(r.get('raw') == 'retained failure' for r in saved.values())
    assert saved['manifest']['inputs']['case'] == CASE['presentation']
    assert saved['manifest']['row_map'] == record['row_map']


@pytest.mark.parametrize('malformed', ['boolean','float','missing','extra','empty','harm','duplicate'])
def test_invalid_complete_reply_does_not_enter_discussion(monkeypatch: pytest.MonkeyPatch, malformed: str) -> None:
    calls = fake_provider(monkeypatch, malformed=malformed)
    record = rand.run_panel(CASE, synthetic_table(), PANEL, save=lambda *_: None)
    assert record['status'] == 'failed' and record['round1'][0]['errors']
    assert len(calls) == 3


def test_disk_preservation_and_fresh_tags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    calls = fake_provider(monkeypatch)
    original = (tmp_path/'answer-tables/Syn002.run1.json').read_bytes()
    path, = rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL)
    record = json.loads(path.read_text())
    assert record['status'] == 'pass' and record['table'] == 'run1'
    assert len(list(path.with_suffix('.receipts').glob('*.json'))) == 11
    assert 'LLM-provisional' in path.with_suffix('.md').read_text()
    assert (tmp_path/'answer-tables/Syn002.run1.json').read_bytes() == original
    with pytest.raises(FileExistsError):
        rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL)
    assert len(calls) == 10
    # Incomplete interrupted tags also block a rerun, even without an aggregate.
    interrupted = path.parent.parent/'interrupted'
    interrupted.mkdir()
    (interrupted/'Syn002.run1-rep1.receipts').mkdir()
    with pytest.raises(FileExistsError):
        rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL, tag='interrupted')
    assert len(calls) == 10


def test_redirected_storage_is_rejected_before_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project=tmp_path/'project'; seed_case(project)
    outside=tmp_path/'outside'; outside.mkdir()
    (project/'results/ratings').mkdir(parents=True)
    (project/'results/ratings/rand').symlink_to(outside, target_is_directory=True)
    calls=fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='redirects'):
        rand.rate(project, 'Syn002', 'run1', 1, PANEL)
    assert not calls


def test_interruption_keeps_input_manifest_and_blocks_reuse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    fake_provider(monkeypatch)
    original = rand._call

    def interrupt(route: dict[str, str], phase: str, payload: dict[str, Any], *args: Any) -> dict[str, Any]:
        if phase == 'rating' and payload['round'] == 1 and route['model'] == 'a':
            raise KeyboardInterrupt('Synthetic interruption')
        return original(route, phase, payload, *args)

    monkeypatch.setattr(rand, '_call', interrupt)
    with pytest.raises(KeyboardInterrupt):
        rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL)
    folder = tmp_path/'results/ratings/rand/Syn002.run1-rep1.receipts'
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['inputs']['case'] and manifest['prompt_sources'] and manifest['reply_schema']
    assert manifest['row_map']['D1']['R1']
    assert not folder.with_suffix('.json').exists()
    with pytest.raises(FileExistsError):
        rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL)


def test_cli_failed_panel_exits_nonzero_with_failure_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    calls = fake_provider(monkeypatch, fail='moderation')
    config = tmp_path/'panel.json'; config.write_text(json.dumps(PANEL))
    monkeypatch.setattr(sys, 'argv', ['noharm','rate',str(tmp_path),'--case','Syn002','--rubric','run1',
                                    '--method','rand','--committee',str(config),'--tag','rand-failed'])
    with pytest.raises(SystemExit) as error:
        noharm.main()
    assert error.value.code == 1 and len(calls) == 7
    record = json.loads((tmp_path/'results/ratings/rand-failed/Syn002.run1-rep1.json').read_text())
    assert record['status'] == 'failed' and record['moderation']['raw'] == 'retained failure'


def test_quick_uses_only_independent_ratings_and_preserves_votes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_provider(monkeypatch)
    table = synthetic_table(); original = copy.deepcopy(table)
    saved: dict[str, Any] = {}
    record = rand.run_panel(CASE, table, PANEL, mode='quick', save=lambda name, value: saved.update({name: value}))
    assert len(calls) == record['planned_calls'] == 3
    assert all(c['phase'] == 'round1' and 'feedback' not in c['payload'] for c in calls)
    assert record['status'] == 'pass' and record['final_rating_round'] == 1
    assert record['method'] == rand.QUICK_METHOD and record['mode'] == 'quick'
    assert record['moderator'] is None and record['moderation'] is None
    assert record['discussion'] == record['round2'] == []
    assert record['aggregate']['options']['D1']['D1.O1']['votes'] == [7,8,9]
    assert record['aggregate']['options']['D1']['D1.O1']['median'] == 8
    assert table == original and record['applied'] is False
    assert len(saved) == 4 and saved['manifest']['mode'] == 'quick'
    assert all(r['provenance']['method'] == rand.QUICK_METHOD for r in record['round1'])
    report = rand.render_report(record, table)
    assert 'RAND quick' in report and 'single-round screening' in report
    assert '| Round 2 median |' not in report and '- Moderator:' not in report


def test_quick_failure_keeps_receipts_without_aggregate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    calls = fake_provider(monkeypatch, fail='round1')
    path, = rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL, mode='quick', tag='quick-failed')
    record = json.loads(path.read_text())
    assert len(calls) == 3 and record['status'] == 'failed' and record['aggregate'] is None
    assert len(list(path.with_suffix('.receipts').glob('*.json'))) == 4
    assert 'failed' in path.with_suffix('.md').read_text()
    with pytest.raises(FileExistsError):
        rand.rate(tmp_path, 'Syn002', 'run1', 1, PANEL, mode='full', tag='quick-failed')
    assert len(calls) == 3


@pytest.mark.parametrize('method,mode,count,folder', [
    ('rand-quick','quick',3,'rand-quick'), ('rand-full','full',10,'rand-full'), ('rand','full',10,'committee'),
])
def test_cli_modes_defaults_and_legacy_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                            method: str, mode: str, count: int, folder: str) -> None:
    seed_case(tmp_path)
    calls = fake_provider(monkeypatch)
    config = tmp_path/'panel.json'; config.write_text(json.dumps(PANEL))
    monkeypatch.setattr(sys, 'argv', ['noharm','rate',str(tmp_path),'--case','Syn002','--rubric','run1',
                                    '--method',method,'--committee',str(config)])
    noharm.main()
    files = list((tmp_path/'results/ratings'/folder).glob('*.json'))
    assert len(files) == 1 and len(calls) == count
    record = json.loads(files[0].read_text())
    assert record['status'] == 'pass' and record['mode'] == mode


def test_rand_cli_rejects_before_calls(tmp_path: Path) -> None:
    quick = ['--method','rand-quick']
    cases: list[tuple[str, list[dict[str, Any]] | None, list[str]]] = [  # label, panel file, extra args
        ('rand-quick with a two-member panel', PANEL[:2], quick),
        *[(' '.join(args), None, args) for args in [
            ['--method','rand'], ['--method','rand','--backend','codex'], ['--workers','2'],
            ['--evidence','evidence.md'], ['--moderator-model','a']]],
        *[(f'rand-quick {flag}', PANEL, [*quick, flag, value]) for flag, value in [
            ('--moderator-backend','codex'), ('--moderator-model','a'), ('--moderator-reasoning-effort','medium')]],
    ]

    def run(case: tuple[str, list[dict[str, Any]] | None, list[str]]) -> None:
        _, panel, args = case
        root = tmp_path / f'row{cases.index(case)}'
        root.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            calls = fake_provider(mp)
            committee: list[str] = []
            if panel is not None:
                config = root/'panel.json'; config.write_text(json.dumps(panel))
                committee = ['--committee', str(config)]
            method, extra = (args[:2], args[2:]) if args[:2] == quick else ([], args)
            mp.setattr(sys, 'argv', ['noharm','rate',str(root),'--case','Syn002','--rubric','run1',
                                     *method, *committee, *extra])
            with pytest.raises(SystemExit) as error:
                noharm.main()
        assert error.value.code == 2 and not calls

    each_case(cases, lambda c: c[0], run)
