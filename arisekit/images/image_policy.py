"""Reusable image generator configuration, separate from its evaluation workload."""

from pathlib import Path
import re

from arisekit.images.image_generation import _runtime_hash, validate_brief
from arisekit.images.imaging import canonical, digest, read_json, write_private

POLICY_SCHEMA = 'arisekit.image-generator.v1'
REQUIRED_CONFIGURATION = {'criteria', 'profiles', 'generator_model', 'critic_model'}
OPTIONAL_CONFIGURATION = {'question_styles', 'original_question_access', 'copy_repair_attempts'}


def _generator_core(brief, runtime_sha256):
    return {'schema_version': POLICY_SCHEMA,
        'configuration': {key: brief[key] for key in sorted(REQUIRED_CONFIGURATION | OPTIONAL_CONFIGURATION) if key in brief},
        'runtime_sha256': runtime_sha256}


def _checked_policy(policy):
    fields = {'schema_version', 'configuration', 'runtime_sha256', 'generator_sha256', 'development'}
    if not isinstance(policy, dict) or set(policy) != fields or policy['schema_version'] != POLICY_SCHEMA:
        raise ValueError('Supply a supported image generator policy')
    config = policy['configuration']
    if (not isinstance(config, dict) or REQUIRED_CONFIGURATION - set(config) or
            set(config) - REQUIRED_CONFIGURATION - OPTIONAL_CONFIGURATION):
        raise ValueError('Generator configuration must exclude evaluation inputs and execution limits')
    if not isinstance(policy['runtime_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', policy['runtime_sha256']):
        raise ValueError('Generator policy requires its frozen runtime hash')
    core = {key: policy[key] for key in ('schema_version', 'configuration', 'runtime_sha256')}
    if digest(core) != policy['generator_sha256']:
        raise ValueError('Generator policy identity does not match its configuration and runtime')
    return policy


def load_image_generator(path):
    """Read a checksum-bound generator without loading any source cases or answers."""
    path = Path(path)
    policy = read_json(path)
    if read_json(path.with_suffix('.sha256.json')) != {'sha256': digest(policy)}:
        raise ValueError('Generator policy checksum differs from its retained artifact')
    return _checked_policy(policy)


def apply_image_generator(policy, brief):
    """Apply the frozen generator while retaining the new evaluation's inputs and limits."""
    policy = _checked_policy(policy)
    if not isinstance(brief, dict):
        raise ValueError('Supply the new image evaluation inputs and execution limits')
    brief = dict(brief)
    if policy['runtime_sha256'] != _runtime_hash():
        raise ValueError('Generator runtime changed; use the saved engine or a new prospective generator')
    if 'profiles' in brief and brief['profiles'] != policy['configuration']['profiles']:
        raise ValueError('Evaluate this generator on the same task profiles')
    for key in OPTIONAL_CONFIGURATION:
        brief.pop(key, None)
    return validate_brief({**brief, **policy['configuration'], 'generator_policy_sha256': policy['generator_sha256']})


def _write_image_generator(path, plan, *, cycle_plan_sha256, selection):
    brief = validate_brief(plan['brief'])
    core = _generator_core(brief, plan['runtime_sha256'])
    policy = {**core, 'generator_sha256': digest(core), 'development': {
        'cycle_plan_sha256': cycle_plan_sha256, 'selected_plan_sha256': digest(plan),
        'source_sha256': plan['source_sha256'], 'selection_rule': selection['rule']}}
    _checked_policy(policy)
    path = Path(path)
    if path.exists():
        if canonical(read_json(path)) != canonical(policy):
            raise ValueError('Retained generator policy changed; preserve it and use a new destination')
        checksum = path.with_suffix('.sha256.json')
        if checksum.exists():
            load_image_generator(path)
        else:
            write_private(checksum, {'sha256': digest(policy)})
    else:
        write_private(path, policy)
        write_private(path.with_suffix('.sha256.json'), {'sha256': digest(policy)})
    return policy
