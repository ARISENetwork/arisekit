"""Release-bound VQA-RAD yes/no tasks with answer-blind public semantic frames."""

from pathlib import Path
import re
import urllib.request

from arisekit.images.imaging import SOURCE_SCHEMA, MAX_ASSET_BYTES, digest, ingest_collection, read_json

SNAPSHOT_SHA256 = '948b7156059b864cf72344fb10669233526b175c243e5a046d20d4201d297a95'
SOURCE_URL = 'https://osf.io/89kps/'


def candidates(snapshot, *, source_policy='paraphrase-frame'):
    payload = Path(snapshot).read_bytes()
    if digest(payload) != SNAPSHOT_SHA256:
        raise ValueError('VQA-RAD question snapshot differs from the pinned official release')
    rows = read_json(Path(snapshot))
    if source_policy not in {'paraphrase-frame', 'original-question'}:
        raise ValueError('Choose paraphrase-frame or original-question source policy')
    if source_policy == 'original-question':
        return [row for row in rows if row['phrase_type'] == 'freeform'
            and row['answer_type'].strip() == 'CLOSED' and row['answer'].strip().lower() in {'yes', 'no'}
            and isinstance(row['question'], str) and row['question'].strip() not in {'NULL', ''}]
    return [row for row in rows if row['phrase_type'] == 'test_para' and row['question_relation'] == 'strict agreement'
        and row['answer_type'].strip() == 'CLOSED' and row['answer'].strip().lower() in {'yes', 'no'}
        and row['question_rephrase'] not in {'NULL', ''} and row['question_frame'] not in {'NULL', ''}]


def connect_vqa_rad(destination, *, snapshot, image_index, question_ids, cache_dir, fetch=None,
                    source_policy='paraphrase-frame'):
    """Keep original, human paraphrase, frame and source answer distinct."""
    pool = {str(row['qid']): row for row in candidates(snapshot, source_policy=source_policy)}
    ids = [str(value) for value in question_ids]
    if not 2 <= len(ids) <= 60 or len(set(ids)) != len(ids) or set(ids) - set(pool):
        raise ValueError('Select 2–60 distinct eligible VQA-RAD question IDs')
    index = {row['attributes']['name']: row for row in read_json(Path(image_index))}
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    def download(url):
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read(MAX_ASSET_BYTES + 1)
    fetch = fetch or download
    assets, records = {}, []
    for identifier in ids:
        row = pool[identifier]
        entry = index[row['image_name']]
        attributes = entry['attributes']
        expected = attributes['extra']['hashes']['sha256']
        url = entry['links']['download']
        if (entry['relationships']['node']['data']['id'] != '89kps' or
            not re.fullmatch(r'https://osf\.io/download/[A-Za-z0-9]+/', url) or
            not re.fullmatch(r'[a-f0-9]{64}', expected) or not 0 < attributes['size'] <= MAX_ASSET_BYTES):
            raise ValueError('Image metadata must identify the official OSF collection, URL and bounded SHA-256 asset')
        name = row['image_name']
        if not re.fullmatch(r'synpic[0-9]+\.jpg', name):
            raise ValueError('Unexpected VQA-RAD image filename')
        path = cache_dir / name
        payload = path.read_bytes() if path.exists() else fetch(url)
        if len(payload) != attributes['size'] or digest(payload) != expected:
            raise ValueError('VQA-RAD image bytes differ from official OSF metadata')
        if not path.exists():
            path.write_bytes(payload)
            path.chmod(0o600)
        assets[name] = payload
        case = re.fullmatch(r'https://medpix\.nlm\.nih\.gov/case\?id=([a-f0-9-]{36})', row['image_case_url'])
        if not case:
            raise ValueError('Source case identity is unavailable; do not invent patient independence')
        records.append({'id': 'vqarad-' + identifier, 'group_id': 'medpix-' + case.group(1), 'group_basis': 'case',
            'field': 'diagnostic radiology', 'modality': 'radiology image', 'images': [name],
            'tags': ['organ:' + row['image_organ'].lower(), 'question-type:' + row['question_type'].lower()],
            'targets': [{'id': 'visual-question', 'profile': 'closed-vqa', 'choices': ['yes', 'no'],
                'answer': row['answer'].strip().lower(), 'question': row['question'], 'question_origin': 'VQA-RAD-original',
                'human_paraphrase': row['question_rephrase'],
                'public_task': {'semantic_frame': (row['question'] if source_policy == 'original-question'
                    else row['question_frame']).strip(), 'question_type': row['question_type']},
                'evidence': 'Official VQA-RAD closed-answer annotation; original/human paraphrase relation is strict agreement.',
                'provenance': {'kind': 'dataset-annotation', 'source': SOURCE_URL, 'snapshot_sha256': SNAPSHOT_SHA256,
                    'qid': identifier, 'linked_id': row['qid_linked_id'], 'case_url': row['image_case_url'],
                    'question_relation': row['question_relation'], 'image_sha256': expected}}]})
        if source_policy == 'original-question':
            target = records[-1]['targets'][0]
            target.pop('human_paraphrase')
            target['evidence'] = 'Official VQA-RAD original freeform closed-answer annotation; no paraphrase-equivalence requirement.'
    manifest = {'schema_version': SOURCE_SCHEMA,
        'authorization': {'authorized': True, 'data_class': 'public', 'provider_permission': True,
            'scope': 'Public VQA-RAD OSF release for local benchmark generation, inference and evaluation.'},
        'source': {'name': 'VQA-RAD', 'revision': SNAPSHOT_SHA256, 'license': 'CC0 1.0 Universal', 'url': SOURCE_URL,
            'citation': 'Lau et al. A dataset of clinically generated visual questions and answers about radiology images. Scientific Data 5, 180251 (2018). doi:10.1038/sdata.2018.251',
            'question_snapshot_sha256': SNAPSHOT_SHA256, 'image_index_sha256': digest(Path(image_index).read_bytes()),
            'source_adapter_sha256': digest(Path(__file__).read_bytes()),
            'selection': {'question_ids': ids, 'policy': 'test_para, strict agreement, closed yes/no, human paraphrase and semantic frame available'},
            'baseline_question_origin': 'Original VQA-RAD questions with standardized finite-answer instructions',
            'human_control': 'Source human paraphrases retained separately; not AI-generated references',
            'patient_ids': 'Unavailable; MedPix case grouping does not establish patient independence'},
        'records': records}
    if source_policy == 'original-question':
        manifest['source']['public_task_policy'] = source_policy
        manifest['source']['selection']['policy'] = 'freeform original, closed yes/no; public original question is the task frame'
        manifest['source']['human_control'] = 'Not supplied by this original-question source policy; no new expert ratings'
    return ingest_collection(destination, manifest, assets)
