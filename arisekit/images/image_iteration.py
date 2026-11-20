"""Development-only diagnosis and retained proposals for image generator revisions."""

from dataclasses import asdict
from collections import Counter
from fractions import Fraction
from pathlib import Path
import json
import math
import shutil

from arisekit.client import ModelCall, resolve_client
from arisekit.dispatch import DispatchLedger
from arisekit.images.image_generation import _json_response, _frozen_plan, _plan, _records, _runtime_hash, _usage, freeze_images, run_images, validate_brief, _invoke_image_request, IMAGE_TRANSPORT_FAILURES, _generated_text
from arisekit.images.image_validation import generation_report
from arisekit.images.imaging import canonical, digest, read_json, verify_collection, write_private
from arisekit.runner import RunnerConfig
from arisekit.sut import SUTResponse
from arisekit.types import BenchmarkItem


def development_diagnosis(root):
    root = Path(root)
    plan = _frozen_plan(root)
    if plan['brief'].get('evaluation_role') != 'development':
        raise ValueError('Generator revision requires an explicitly declared development run')
    if set(_records(root)['completed']) != set(plan['steps']):
        raise ValueError('Finish the complete development panel before diagnosing a revision')
    report = generation_report(root)
    completed = _records(root)['completed']
    task_types = {}
    for item in plan['originals']:
        contract = plan.get('public_task_contracts', {}).get(item['id'])
        if contract:
            key = (item['metadata']['source_id'], item['metadata']['target_id'])
            task_types[key] = contract['task_contract'].get('question_type', item['metadata']['profile'])
    return {'parent_plan_sha256': digest(plan), 'report_sha256': digest(report),
        'criteria': plan['brief']['criteria'], 'question_styles': plan['brief'].get('question_styles', []),
        'profiles': {profile: {'calibration': values['calibration'], 'concordance': values['concordance'],
            'models': values['models'], 'paired_score_diagnostics': values['paired_score_diagnostics']}
            for profile, values in report['profiles'].items()},
        'wording': {'copied_original': sum(row['exact_original_question'] for row in report['originality']['per_task']),
            'original_question_access': plan['brief'].get('original_question_access', False),
            'prefix_only_original_copies': sum(row['prefix_only_original_copy'] for row in report['originality']['per_task']),
            'task_type_counts': dict(Counter(task_types.values())),
            'declared_contract_checks': {key: value for key, value in report['declared_contract_checks'].items() if key != 'per_task'},
            'declared_contract_examples': [json.loads(value) for value in
                dict.fromkeys(canonical(value) for value in plan.get('public_task_contracts', {}).values())][:4],
            'duplicate_stem_group_sizes': [len(group) for group in report['originality']['exact_duplicate_question_groups']],
            'lexical_overlaps': [row['question_token_jaccard'] for row in report['originality']['per_task']],
            'original_task_templates': list(dict.fromkeys(row['prompt'].split('\nAnswer with exactly one label from: ')[0][:300]
                for row in plan['originals']))[:3],
            'generated_question_examples': list(dict.fromkeys(_json_response(_generated_text(plan, completed, item['id']))['question'][:240]
                for item in plan['originals']))[:4]},
        'ai_issues': [issue for row in report['ai_review'] for issue in row['issues']]}


def _calibration_key(profiles):
    errors = [[abs(Fraction(row['generated']['correct'], row['generated']['assigned']) -
                   Fraction(row['original']['correct'], row['original']['assigned']))
               for row in profile['models']] for profile in profiles.values()]
    return (sum(sum(values) / len(values) for values in errors) / len(errors),
            max(value for values in errors for value in values),
            sum((profile['concordance'] or {}).get('discordant', 0) for profile in profiles.values()))


def select_development_revision(roots):
    if not roots:
        raise ValueError('Supply completed development runs')
    diagnoses = [development_diagnosis(root) for root in roots]
    plans = [_frozen_plan(Path(root)) for root in roots]
    if len({canonical({'source': plan['source_sha256'], 'models': plan['brief']['models'],
                       'originals': plan['originals']}) for plan in plans}) != 1:
        raise ValueError('Development selection requires identical source, model panel and original tasks')
    candidates = []
    for root, diagnosis in zip(roots, diagnoses):
        values = diagnosis['profiles']
        key = _calibration_key(values)
        candidates.append({'run': str(root), 'plan_sha256': diagnosis['parent_plan_sha256'],
                           'selection_key': [float(key[0]), float(key[1]), key[2]]})
    selected = min(range(len(candidates)), key=lambda i: (*candidates[i]['selection_key'], i))
    return {'selected': candidates[selected], 'candidates': candidates,
            'rule': 'Development mean absolute score error, then maximum error, then reversed source pairs; first frozen candidate breaks remaining ties.'}


def propose_image_revision(root, destination, *, client, max_cost=.025, max_cost_per_call=None):
    """Use development feedback to propose next-run criteria without item edits."""
    root, destination = Path(root), Path(destination)
    diagnosis = development_diagnosis(root)
    plan = _frozen_plan(root)
    client = resolve_client(client)
    per_call = max_cost if max_cost_per_call is None else max_cost_per_call
    retries = plan['brief'].get('transport_retries', 0)
    if getattr(client, 'model', None) != plan['brief']['critic_model']:
        raise ValueError('Use the frozen critic route for development revision proposals')
    task_scope = ('Preserve the clinical task, complete released taxonomy and whole-image classification objective. '
        if plan['brief']['profiles'] == ['classification'] else
        'Preserve each public semantic frame and its exact yes/no visual decision, including polarity, anatomy, laterality, quantities and comparisons. '
        if plan['brief']['profiles'] == ['closed-vqa'] else
        'Preserve every declared classification taxonomy and visual question task, including each supplied public frame and answer vocabulary. ')
    if plan['brief'].get('original_question_access'):
        task_scope = ('The public original question defines each exact clinical decision and all qualifiers; the frame is secondary. '
            'Preserve every supplied task type, not just presence. Require different grammar beyond prepending an image-context opening. ')
    system = ('Improve the next medical image question generator from this development-only diagnosis. ' + task_scope +
        'Propose concise generation criteria that produce novel, varied question forms while preserving model comparisons and score calibration. '
        'Do not tune to individual models, reveal answers, copy original wording, change choices or scoring, add visual hints, '
        'or make questions easier to inflate accuracy. No case reference answers, image pixels or model identities are supplied. '
        'Original task templates and generated examples are provided for semantic diagnosis. Identify lost task context and wording conflicts. '
        'Do not quote or pass original questions verbatim in the revised criteria. Critique comments are AI judgments, not reference facts. '
        'Complementary agreement metrics diagnose distortion; retain stable OG comparisons and absolute score calibration together. '
        'For short rosters, interpret RBO using observed-prefix overlap and its reported tail rather than the extrapolated value alone. '
        'Use consistent task context while varying sentence structure and obeying the declared styles. '
        'Frozen public task contracts and style rules are immutable; remove conflicting criteria instead of overriding those rules. '
        'Return only JSON with criteria (string, at most 1400 characters), diagnosis (string), changes (array of strings).')
    schema = {'type': 'object', 'properties': {'criteria': {'type': 'string'},
        'diagnosis': {'type': 'string'}, 'changes': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['criteria', 'diagnosis', 'changes'], 'additionalProperties': False}
    feedback = {'criteria': diagnosis['criteria'], 'question_styles': diagnosis['question_styles'],
        'wording': {key: value for key, value in diagnosis['wording'].items() if key != 'lexical_overlaps'},
        'profiles': {profile: {'calibration': {key: values['calibration'][key] for key in
            ('mean_absolute_score_error', 'maximum_absolute_score_error', 'root_mean_squared_score_error')},
            'rank_pairs': values['concordance'], 'paired_score_diagnostics': values['paired_score_diagnostics'],
            'anonymous_model_results': [
                {'original_score': row['original']['accuracy'], 'generated_score': row['generated']['accuracy'],
                 'assigned': row['original']['assigned'], 'prediction_changes': row['prediction_changes']}
                for row in values['models']]} for profile, values in diagnosis['profiles'].items()},
        'ai_issue_examples': list(dict.fromkeys(issue[:240] for issue in diagnosis['ai_issues']))[:3]}
    prompt = canonical(feedback)
    frozen = {'parent_plan_sha256': digest(plan), 'diagnosis_sha256': digest(diagnosis), 'model': client.model,
        'system': system, 'prompt': prompt, 'schema': schema, 'max_cost': max_cost,
        'max_cost_per_call': per_call, 'transport_retries': retries,
        'runtime_sha256': digest(Path(__file__).read_bytes())}
    path = destination / 'revision-plan.json'
    if path.exists():
        if read_json(path) != frozen:
            raise ValueError('Revision inputs changed; retain this proposal and use a new destination')
    else:
        write_private(path, frozen)
    ledger = DispatchLedger(destination / 'image-dispatch.jsonl', RunnerConfig(max_calls=retries + 1,
        max_cost=max_cost, max_cost_per_call=per_call, require_known_cost=True), {},
        reserved_failure_types=IMAGE_TRANSPORT_FAILURES if retries else frozenset())
    call = ModelCall(BenchmarkItem(id='criteria-revision', prompt=prompt,
        metadata={'image_step': 'revise:criteria', 'image_condition': 'taxonomy-only'}),
        system_prompt=system, temperature=0, max_tokens=1600,
        extra={'response_format': {'type': 'json_schema', 'json_schema': {'name': 'image_revision', 'strict': True, 'schema': schema}}})
    def invoke():
        response = client(call)
        return SUTResponse(response=response.text, cost=response.cost, cost_known=response.cost_known,
            tokens_in=response.tokens_in, tokens_out=response.tokens_out, finish_reason=response.finish_reason,
            provider_model=response.provider_model, response_id=response.response_id)
    try:
        response = _invoke_image_request(ledger, ('revise:criteria', 1), digest(frozen), invoke,
            root=destination, retries=retries)
        write_private(destination / 'response.json', asdict(response))
        proposal = _json_response(response.response)
        if (set(proposal) != {'criteria', 'diagnosis', 'changes'} or not isinstance(proposal['criteria'], str) or
            not 1 <= len(proposal['criteria'].strip()) <= 1400 or not isinstance(proposal['diagnosis'], str) or
            not isinstance(proposal['changes'], list) or any(not isinstance(change, str) for change in proposal['changes'])):
            raise ValueError('Retained revision proposal is structurally invalid')
        write_private(destination / 'proposal.json', proposal)
        return proposal
    finally:
        ledger.close()


def run_development_cycles(root, *, source, brief, generator, critic, solvers, rounds=3, max_cost):
    """Generate, evaluate, diagnose and propose the next frozen development round."""
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError('Choose 1–10 bounded development rounds')
    brief = validate_brief(brief)
    if 'generator_policy_sha256' in brief:
        from arisekit.images.image_policy import _generator_core
        if digest(_generator_core(brief, _runtime_hash())) != brief['generator_policy_sha256']:
            raise ValueError('Generator policy identity differs from the starting generator; use a new revision identity')
    if brief.get('evaluation_role') != 'development':
        raise ValueError('Automatic cycles require an explicitly declared development brief')
    if type(max_cost) not in {int, float} or not math.isfinite(max_cost) or not 0 < rounds * Fraction(str(brief['max_cost'])) <= Fraction(str(max_cost)):
        raise ValueError('The cycle budget must cover the declared bounded rounds')
    proposal_bound = float((brief.get('transport_retries', 0) + 1) * Fraction(str(brief['max_cost_per_call'])))
    if Fraction(str(brief['max_cost'])) - Fraction(str(proposal_bound)) < Fraction(str(brief['max_cost_per_call'])):
        raise ValueError('Leave room for a revision proposal within each round budget')
    root, source = Path(root), Path(source)
    frozen = {'source_sha256': digest(verify_collection(source)), 'brief': brief,
              'selection_rule': 'comparison-preserving-novel-forms-v1',
              'rounds': rounds, 'max_cost': max_cost, 'runtime_sha256': _runtime_hash()}
    path = root / 'cycle-plan.json'
    if path.exists():
        if read_json(path) != frozen:
            raise ValueError('The frozen cycle changed; preserve it and use a new root')
    else:
        write_private(path, frozen)
    completed = []
    criteria = brief['criteria']
    for index in range(rounds):
        if index:
            proposal = propose_image_revision(completed[-1], root / f'revision-{index}',
                client=critic, max_cost=proposal_bound, max_cost_per_call=brief['max_cost_per_call'])
            criteria = proposal['criteria']
        current = root / f'round-{index + 1}'
        config = {**brief, 'criteria': criteria,
                  'max_cost': float(Fraction(str(brief['max_cost'])) - (Fraction(str(proposal_bound)) if index else 0))}
        config.pop('generator_policy_sha256', None)
        if not (current / 'image-plan.json').exists():
            if not (current / 'source').exists():
                current.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copytree(source, current / 'source')
            if digest(verify_collection(current / 'source')) != frozen['source_sha256']:
                raise ValueError('The development source copy differs from the frozen cycle')
            freeze_images(current, config)
        elif _plan(current)['brief'] != config:
            raise ValueError('The retained round differs from its frozen revision')
        status = run_images(current, generator=generator, critic=critic, solvers=solvers)
        if status['status'] != 'complete':
            result = {'status': 'stopped', 'run': str(current), 'detail': status}
            write_private(root / 'cycle-progress.json', result)
            return result
        write_private(current / 'generation-validation.json', generation_report(current))
        write_private(current / 'diagnosis.json', development_diagnosis(current))
        completed.append(current)
        write_private(root / 'cycle-progress.json', {'status': 'running', 'completed_rounds': index + 1})
    from arisekit.images.image_selection import select_comparison_preserving_revision
    from arisekit.images.image_policy import _write_image_generator
    selection = select_comparison_preserving_revision(completed, allow_no_selection=True)
    usage = [_usage(run) for run in completed] + [_usage(root / f'revision-{i}') for i in range(1, rounds)]
    result = {'status': 'complete' if selection['selected'] else 'no-eligible-candidate',
        **selection, 'cost': sum(row['cost'] for row in usage),
        'provider_calls': sum(row['provider_calls'] for row in usage), 'cost_unknown': any(row['cost_unknown'] for row in usage)}
    if selection['selected']:
        selected = _plan(Path(selection['selected']['run']))
        policy = _write_image_generator(root / 'generator-policy.json', selected,
            cycle_plan_sha256=digest(frozen), selection=selection)
        result.update(selected_brief=selected['brief'], generator_policy='generator-policy.json',
            generator_policy_sha256=policy['generator_sha256'])
    else:
        result['reason'] = 'All rounds completed, but none supplied distinct non-copied forms. No generator policy was selected.'
    write_private(root / 'cycle-result.json', result)
    return result
