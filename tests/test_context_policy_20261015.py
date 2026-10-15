"""Regression coverage for the October 2026 Register context policy."""
import os
from datetime import datetime, timezone
import pytest

os.environ['AUTO_SUMMARY'] = 'false'
os.environ['HERALD_STATUS_EXPORT'] = 'false'

import checkpoints as cp
import register as reg
import app


def _body(payload):
    sections = '\n'.join(f'{name}\n- {payload if name == "ARCH" else name}'
                          for name in cp.SECTIONS)
    return '## Human summary\nDemo useful.\n\n## AI checkpoint\nCTX/2\n' + sections


def _meta():
    return {'checkpoint_version': 1, 'project': 'Demo', 'based_on': 'ROOT',
            'created_at': '2026-10-15T22:00:00Z'}


def test_checkpoint_cap_accepts_20k_warns_at_15k_and_rejects_25k():
    assert cp.MAX_TOKENS == cp.WARNING_TOKENS == 15000
    assert cp.HARD_MAX_TOKENS >= 25000
    medium = _body('x' * 80000)
    assert 15000 < reg._estimate_tokens(medium) <= cp.HARD_MAX_TOKENS
    assert cp.parse(_meta(), medium, 'Demo')['context'].startswith('CTX/2')
    too_long = _body('x' * (4 * cp.HARD_MAX_TOKENS))
    with pytest.raises(ValueError, match='exceeds'):
        cp.parse(_meta(), too_long, 'Demo')


def test_lossless_mode_preserves_all_sections_and_unprotected_details():
    full = 'CTX/2\n' + '\n'.join(
        f'{sec}\n- information specific to {sec}: /srv/project/{sec}.py'
        for sec in cp.SECTIONS)
    out = reg.compress_documents([('ctx.md', full)])
    assert out['status'] == 'generated' and out['lossy'] is False
    assert out['verified'] and out['omitted_units'] == 0
    assert out['context'] == full
    for sec in cp.SECTIONS:
        assert f'/srv/project/{sec}.py' in out['context']


def test_lossless_multiple_sources_keep_entire_contents_and_boundaries():
    a = '## Goal\n- First technical /srv/first.py'
    b = '## Goal\n- Second technical /srv/second.py'
    out = reg.compress_documents([('one.md', a), ('two.md', b)])
    assert out['status'] == 'generated' and out['lossy'] is False
    assert a in out['context'] and b in out['context']
    assert 'SOURCE_FILE 1: one.md' in out['context']
    assert 'SOURCE_FILE 2: two.md' in out['context']


def test_selective_reports_nonprotected_losses_not_as_verified():
    body = 'CTX/2\nGOAL\n- Demo project.\nARCH\n' + '\n'.join(
        f'- feature{i} module{i} method{i} endpoint{i} schema{i} distinct{i} details{i}.'
        for i in range(120))
    out = reg.compress_documents([('ctx.md', body)], mode='dense', target_tokens=1000)
    assert out['status'] == 'generated' and out['lossy'] is True
    assert out['verified'] is False
    assert out['section_coverage']['ARCH']['retained_units'] >= 1
    assert out['section_coverage']['ARCH']['omitted_units'] > 0
    assert out['omitted_units'] > 0


def test_handoff_prompt_contains_live_cap_and_explicit_preflight():
    prompt = app._prompt_text('handoff')
    assert str(cp.HARD_MAX_TOKENS) in prompt
    assert 'Target no more than' in prompt
    assert 'round(character_count / 4)' in prompt
    assert '<HANDOFF_HARD_MAX_TOKENS>' not in prompt
    assert 'NEVER output a larger document' in prompt
