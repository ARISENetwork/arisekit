import io
import json
from pathlib import Path

import pytest
from PIL import Image

from arisekit.client import ModelResponse, _build_messages
from arisekit.images.image_generation import freeze_images, run_images
from arisekit.images.image_validation import generation_report
from arisekit.images.imaging import digest, ingest_collection, verify_collection
from arisekit.images import vqa_rad
from test_imaging import brief, collection


def fixture(tmp_path, monkeypatch):
    rows, index, assets = [], [], {}
    for i in range(4):
        buffer = io.BytesIO()
        Image.new('RGB', (12, 12), (20 + i * 40, 40, 60)).save(buffer, format='JPEG')
        payload = buffer.getvalue()
        name, url = f'synpic{i}.jpg', f'https://osf.io/download/abc{i}/'
        assets[url] = payload
        rows.append({'qid': i, 'phrase_type': 'test_para', 'question_relation': 'strict agreement',
            'answer_type': 'CLOSED', 'answer': 'Yes' if i % 2 else 'No',
            'question': 'PRIVATE original wording ' + str(i), 'question_rephrase': 'PRIVATE human wording ' + str(i),
            'question_frame': f'Is feature {i} visible?', 'question_type': 'PRES', 'image_organ': 'CHEST',
            'image_name': name, 'qid_linked_id': str(i),
            'image_case_url': f'https://medpix.nlm.nih.gov/case?id={i:08d}-0000-0000-0000-000000000000'})
        index.append({'attributes': {'name': name, 'size': len(payload), 'extra': {'hashes': {'sha256': digest(payload)}}},
            'links': {'download': url}, 'relationships': {'node': {'data': {'id': '89kps'}}}})
    snapshot, image_index = tmp_path / 'questions.json', tmp_path / 'images.json'
    snapshot.write_text(json.dumps(rows)); image_index.write_text(json.dumps(index))
    monkeypatch.setattr(vqa_rad, 'SNAPSHOT_SHA256', digest(snapshot.read_bytes()))
    return rows, snapshot, image_index, assets


def test_pinned_source_preserves_native_questions_human_controls_and_references(tmp_path, monkeypatch):
    rows, snapshot, image_index, assets = fixture(tmp_path, monkeypatch)
    calls = []
    def fetch(url):
        calls.append(url)
        return assets[url]
    kwargs = dict(snapshot=snapshot, image_index=image_index, question_ids=range(4), cache_dir=tmp_path / 'cache', fetch=fetch)
    source = vqa_rad.connect_vqa_rad(tmp_path / 'source', **kwargs)
    assert len(calls) == 4 and verify_collection(tmp_path / 'source') == source
    for row in source['records']:
        target = row['targets'][0]
        assert row['group_basis'] == 'case' and target['question_origin'] == 'VQA-RAD-original'
        assert target['answer'] in {'yes', 'no'} and target['human_paraphrase'].startswith('PRIVATE human')
        assert set(target['public_task']) == {'semantic_frame', 'question_type'}
        assert target['provenance']['kind'] == 'dataset-annotation'
    vqa_rad.connect_vqa_rad(tmp_path / 'second', **kwargs)
    assert len(calls) == 4
    snapshot.write_text('[]')
    with pytest.raises(ValueError, match='pinned official release'):
        vqa_rad.candidates(snapshot)


def test_image_hash_or_foreign_osf_metadata_is_rejected(tmp_path, monkeypatch):
    rows, snapshot, index, assets = fixture(tmp_path, monkeypatch)
    kwargs = dict(snapshot=snapshot, image_index=index, question_ids=[0, 1], cache_dir=tmp_path / 'cache')
    with pytest.raises(ValueError, match='differ from official'):
        vqa_rad.connect_vqa_rad(tmp_path / 'wrong-bytes', fetch=lambda url: b'wrong', **kwargs)
    values = json.loads(index.read_text()); values[0]['links']['download'] = 'https://example.com/foreign.jpg'
    index.write_text(json.dumps(values))
    with pytest.raises(ValueError, match='official OSF'):
        vqa_rad.connect_vqa_rad(tmp_path / 'foreign', fetch=lambda url: assets[url], **kwargs)


class Client:
    def __init__(self, model, calls): self.model, self.calls = model, calls
    def __call__(self, call):
        messages = _build_messages(call)
        step = call.item.metadata['image_step']
        self.calls.append((self.model, call, messages))
        if step.startswith('generate:'):
            data = json.loads(call.item.prompt)
            assert call.item.metadata['image_condition'] == ('original-and-frame-only' if 'original_question' in data['task_contract'] else 'frame-only') and not call.item.attachments
            assert set(data['source_target']) == {'id', 'profile', 'choices', 'public_task'}
            assert 'PRIVATE' not in call.item.prompt
            frame = data['task_contract']['semantic_frame']
            prefix = 'In this image, is ' if data['question_style'] == 'clinical-direct' else 'Does the image show '
            text = json.dumps({'question': prefix + frame[3:], 'target_id': data['source_target']['id'],
                'grounding': 'Synthetic frame fixture', 'uncertainty': 'Engineering check only'})
        elif step.startswith('review:'):
            data = json.loads(call.item.prompt)
            assert call.item.attachments and 'PRIVATE' not in call.item.prompt
            assert 'reviewer_only_reference' not in data and 'answer' not in data['task_definition']
            text = json.dumps({'grounded': True, 'criteria_aligned': True, 'issues': [], 'uncertainty': 'Engineering fixture'})
        else: text = 'yes'
        return ModelResponse(text=text, cost=.001, cost_known=True)


@pytest.mark.parametrize('original_access', [False, True])
def test_frame_only_generation_and_review_are_invariant_to_private_wording_and_answers(tmp_path, monkeypatch, original_access):
    rows, snapshot, index, assets = fixture(tmp_path, monkeypatch)
    if original_access:
        for row in rows:row['question']=f"Is feature {row['qid']} visible in the left lung?"
        snapshot.write_text(json.dumps(rows));monkeypatch.setattr(vqa_rad,'SNAPSHOT_SHA256',digest(snapshot.read_bytes()))
    authoring = []
    for variant in range(2):
        root = tmp_path / str(variant)
        if variant:
            for row in rows:
                row.update(answer='No' if row['answer'] == 'Yes' else 'Yes',
                    question=row['question'] if original_access else 'PRIVATE changed original', question_rephrase='PRIVATE changed human')
            snapshot.write_text(json.dumps(rows)); monkeypatch.setattr(vqa_rad, 'SNAPSHOT_SHA256', digest(snapshot.read_bytes()))
        source = vqa_rad.connect_vqa_rad(root / 'source', snapshot=snapshot, image_index=index,
            question_ids=range(4), cache_dir=tmp_path / 'cache', fetch=lambda url: assets[url])
        freeze_images(root, brief(field='diagnostic radiology', profiles=['closed-vqa'], models=['solver'],
            case_count=4, evaluation_fraction=1, question_styles=['clinical-direct', 'clinical-rephrase'],
            evaluation_role='development', max_calls=32, original_question_access=original_access))
        plan = json.loads((root / 'image-plan.json').read_text())
        assert plan['closed_vqa_reference_access'] == ('Source-answer-blind; public original question and frame' if original_access else 'public-frame-only')
        assert plan['authoring_original_question_access'] is original_access
        assert all(('original_question' in value['task_contract']) is original_access for value in plan['public_task_contracts'].values())
        assert plan['classification_reference_access'] == 'not-requested'
        calls = []
        assert run_images(root, generator=Client('writer', calls), critic=Client('reviewer', calls),
            solvers={'solver': Client('solver', calls)})['status'] == 'complete'
        authoring.append([messages for model, call, messages in calls if model in {'writer', 'reviewer'}])
        report = generation_report(root, bootstrap=10)
        assert report['declared_contract_checks']['structural_conflicts'] == 0
        assert report['profiles']['closed-vqa']['models'][0]['generated']['assigned'] == 8
    assert authoring[0] == authoring[1]


def test_clinical_styles_cannot_expose_legacy_vqa_answer_evidence(tmp_path):
    manifest, assets = collection(4, profiles=('closed-vqa',))
    ingest_collection(tmp_path / 'source', manifest, assets)
    with pytest.raises(ValueError, match='public semantic frame'):
        freeze_images(tmp_path, brief(profiles=['closed-vqa'], question_styles=['clinical-direct'],
            case_count=4, evaluation_fraction=1))


def test_original_question_access_is_explicit_and_task_bounded():
    from arisekit.images.image_generation import validate_brief
    with pytest.raises(ValueError, match='explicit boolean'):
        validate_brief(brief(profiles=['classification'], question_styles=['direct'], original_question_access=True))
    with pytest.raises(ValueError, match='explicit boolean'):
        validate_brief(brief(profiles=['closed-vqa'], question_styles=['clinical-direct'], original_question_access=1))


def test_image_context_prefix_is_not_substantive_rewording():
    from dataclasses import replace
    from arisekit.images.image_generation import _diagnostics
    from arisekit.types import BenchmarkItem
    original=BenchmarkItem(id='a',prompt='Is the heart enlarged?',ground_truth='yes',metadata={
        'profile':'closed-vqa','source_id':'case','target_id':'question','question_style':'clinical-direct'})
    copied=replace(original,prompt='In this image, is the heart enlarged?')
    novel=replace(original,prompt='In this image, does the heart show enlargement?')
    assert _diagnostics([original],[copied])['per_task'][0]['prefix_only_original_copy']
    assert not _diagnostics([original],[novel])['per_task'][0]['prefix_only_original_copy']


def test_original_question_pool_preserves_answers_without_paraphrase_or_frame(tmp_path, monkeypatch):
    rows, snapshot, index, assets = fixture(tmp_path, monkeypatch)
    for row in rows:
        row.update(phrase_type='freeform', question=f"Is feature {row['qid']} visible in the left lung?",
                   question_rephrase=None, question_frame=None, question_relation='NULL')
    snapshot.write_text(json.dumps(rows))
    monkeypatch.setattr(vqa_rad, 'SNAPSHOT_SHA256', digest(snapshot.read_bytes()))
    assert vqa_rad.candidates(snapshot) == []
    assert len(vqa_rad.candidates(snapshot, source_policy='original-question')) == 4
    root = tmp_path / 'run'
    source = vqa_rad.connect_vqa_rad(root / 'source', snapshot=snapshot, image_index=index,
        question_ids=range(4), cache_dir=tmp_path / 'cache', fetch=lambda url: assets[url],
        source_policy='original-question')
    assert source['source']['public_task_policy'] == 'original-question'
    for source_row, released in zip(source['records'], rows):
        target = source_row['targets'][0]
        assert target['answer'] == released['answer'].lower()
        assert target['public_task']['semantic_frame'] == released['question']
        assert 'human_paraphrase' not in target
    config = brief(field='diagnostic radiology', profiles=['closed-vqa'], models=['solver'],
        case_count=4, evaluation_fraction=1, question_styles=['clinical-direct','clinical-alternate'], max_calls=32)
    with pytest.raises(ValueError, match='explicit original-question access'):
        freeze_images(root, config)
    freeze_images(root, {**config, 'original_question_access': True})
    calls = []
    assert run_images(root, generator=Client('writer',calls), critic=Client('reviewer',calls),
        solvers={'solver':Client('solver',calls)})['status'] == 'complete'
    plan = json.loads((root / 'image-plan.json').read_text())
    alternate = [v for v in plan['public_task_contracts'].values() if v['question_style']=='clinical-alternate']
    assert all(v['starts_with'] is None and v['ends_with_question_mark'] for v in alternate)
    assert all(not call.item.attachments for model,call,_ in calls if model=='writer')


def test_alternate_style_still_rejects_image_prefix_copies():
    from dataclasses import replace
    from arisekit.images.image_generation import _diagnostics,validate_brief
    from arisekit.types import BenchmarkItem
    config=brief(profiles=['closed-vqa'],question_styles=['clinical-alternate'],original_question_access=True)
    assert validate_brief(config)['question_styles']==['clinical-alternate']
    original=BenchmarkItem(id='a',prompt='Is the heart enlarged?',ground_truth='yes',metadata={
        'profile':'closed-vqa','source_id':'case','target_id':'question','question_style':'clinical-alternate'})
    copied=replace(original,prompt='In this image, is the heart enlarged?')
    assert _diagnostics([original],[copied])['per_task'][0]['prefix_only_original_copy']
