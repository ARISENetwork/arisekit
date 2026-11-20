import json
from pathlib import Path

import pytest

from arisekit.client import ModelResponse
from arisekit.dispatch import DispatchLedger, DispatchStopped
from arisekit.images.image_generation import IMAGE_TRANSPORT_FAILURES, _invoke_image_request, validate_brief
from arisekit.images.image_iteration import run_development_cycles
from arisekit.images.imaging import ingest_collection
from arisekit.runner import RunnerConfig
from arisekit.sut import SUTResponse
from test_imaging import ImageClient, brief, collection
from test_image_iteration import StyleWriter


@pytest.mark.parametrize('value', [-1, 3, True, 1.5, '1'])
def test_transport_attempt_limit_is_explicit_and_bounded(value):
    with pytest.raises(ValueError, match='transport retries'):
        validate_brief(brief(transport_retries=value))


def ledger(root, *, max_cost=1, max_calls=20, enabled=True):
    return DispatchLedger(root / 'calls.jsonl', RunnerConfig(max_cost=max_cost, max_calls=max_calls,
        max_cost_per_call=.025, require_known_cost=True), {},
        reserved_failure_types=IMAGE_TRANSPORT_FAILURES if enabled else frozenset())


def test_timeout_reservation_survives_success_and_resume_does_not_reinfer(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr('arisekit.images.image_generation.time.sleep', waits.append)
    calls = []
    def invoke():
        calls.append('call')
        if len(calls) == 1:
            raise TimeoutError('transport failed')
        return SUTResponse('yes', cost=.001, cost_known=True)
    journal = ledger(tmp_path)
    assert _invoke_image_request(journal, ('step', 1), 'signature', invoke, root=tmp_path, retries=1).response == 'yes'
    assert journal.usage()['cost'] == .026 and journal.usage()['cost_unknown']
    assert waits == [5]
    journal.close()
    resumed = ledger(tmp_path)
    assert _invoke_image_request(resumed, ('step', 1), 'signature', invoke, root=tmp_path, retries=1).response == 'yes'
    resumed.close()
    assert len(calls) == 2
    failure = json.loads(next((tmp_path / 'transport-failures').glob('*.json')).read_text())
    assert failure['cost_known'] is False and failure['retained_cost_reservation'] == .025


def test_attempt_limit_is_retained_across_restart(tmp_path, monkeypatch):
    monkeypatch.setattr('arisekit.images.image_generation.time.sleep', lambda _: None)
    calls = []
    def fail():
        calls.append('call')
        raise TimeoutError('blocked')
    for run in range(2):
        journal = ledger(tmp_path)
        with pytest.raises(DispatchStopped, match='retry limit'):
            _invoke_image_request(journal, ('step', 1), 'signature', fail, root=tmp_path, retries=2)
        assert journal.usage()['provider_calls'] == 3
        assert journal.usage()['cost'] == .075
        journal.close()
    assert len(calls) == 3


@pytest.mark.parametrize('mode', ['disabled', 'unclassified', 'unknown-success'])
def test_recovery_does_not_waive_unapproved_failures_or_unknown_success(tmp_path, monkeypatch, mode):
    monkeypatch.setattr('arisekit.images.image_generation.time.sleep', lambda _: None)
    calls = []
    def invoke():
        calls.append('call')
        if mode == 'unknown-success':
            return SUTResponse('yes', cost_known=False)
        raise TimeoutError('timeout') if mode == 'disabled' else ValueError('malformed input')
    journal = ledger(tmp_path, enabled=mode != 'disabled')
    with pytest.raises(DispatchStopped, match='unknown'):
        _invoke_image_request(journal, ('step', 1), 'signature', invoke, root=tmp_path,
                              retries=0 if mode == 'disabled' else 2)
    journal.close()
    assert len(calls) == 1


@pytest.mark.parametrize('limits,reason', [({'max_calls': 1}, 'call budget'), ({'max_cost': .025}, 'budget')])
def test_total_execution_limits_override_retry_allowance(tmp_path, monkeypatch, limits, reason):
    monkeypatch.setattr('arisekit.images.image_generation.time.sleep', lambda _: None)
    calls = []
    def fail():
        calls.append('call')
        raise TimeoutError('failed')
    journal = ledger(tmp_path, **limits)
    with pytest.raises(DispatchStopped, match=reason):
        _invoke_image_request(journal, ('step', 1), 'signature', fail, root=tmp_path, retries=2)
    journal.close()
    assert calls == ['call']


def test_pending_interruption_does_not_become_an_approved_retry(tmp_path):
    initial = ledger(tmp_path)
    initial.close()
    with (tmp_path / 'calls.jsonl').open('a') as handle:
        handle.write(json.dumps({'schema_version': 'arisekit.dispatch.v1',
            'call_id': 'pending', 'run_id': 'old-process', 'item': 'step', 'trial': 1,
            'signature': 'signature', 'state': 'reserved', 'accounted_cost': .025}) + '\n')
    journal = ledger(tmp_path)
    calls = []
    with pytest.raises(DispatchStopped, match='unknown'):
        _invoke_image_request(journal, ('step', 1), 'signature', lambda: calls.append('unexpected'), root=tmp_path, retries=2)
    journal.close()
    assert calls == []


def test_full_cycle_recovers_revision_and_separates_attempt_and_round_budgets(tmp_path, monkeypatch):
    monkeypatch.setattr('arisekit.images.image_generation.time.sleep', lambda _: None)
    manifest, assets = collection(2, profiles=('classification',))
    source = tmp_path / 'source'
    ingest_collection(source, manifest, assets)
    calls = []
    class Critic(ImageClient):
        revision_attempts = 0
        def __call__(self, call):
            if call.item.metadata['image_step'] == 'revise:criteria':
                self.revision_attempts += 1
                if self.revision_attempts == 1:
                    raise TimeoutError('transient revision transport')
                return ModelResponse(text=json.dumps({'criteria': 'Preserve the visual task and taxonomy; use distinct sentence forms.',
                    'diagnosis': 'Preserve task scope', 'changes': ['Use distinct grammar']}), cost=.001, cost_known=True)
            return super().__call__(call)
    critic = Critic('reviewer', calls)
    config = brief(profiles=['classification'], case_count=2, evaluation_fraction=1, models=['vision-a', 'vision-b'],
        question_styles=['direct', 'selection'], evaluation_role='development', max_calls=30, max_cost=1, max_cost_per_call=.025,
        transport_retries=1)
    root = tmp_path / 'cycle'
    kwargs = dict(source=source, brief=config, generator=StyleWriter('writer', calls), critic=critic,
        solvers={m: ImageClient(m, calls) for m in config['models']}, rounds=2, max_cost=2)
    result = run_development_cycles(root, **kwargs)
    assert result['status'] == 'complete' and result['cost_unknown']
    assert result['provider_calls'] == 50 and critic.revision_attempts == 2
    proposal = json.loads((root / 'revision-1/revision-plan.json').read_text())
    assert proposal['max_cost'] == .05 and proposal['max_cost_per_call'] == .025
    assert json.loads((root / 'round-2/image-plan.json').read_text())['brief']['max_cost'] == .95
    assert (root / 'generator-policy.json').exists()
    assert run_development_cycles(root, **kwargs) == result
    assert critic.revision_attempts == 2
