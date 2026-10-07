import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import register as reg

@pytest.fixture
def vault(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(reg, 'VAULT_PATH', Path(d))
        root = Path(d)/'projects'/'Demo'
        (root/'handoffs').mkdir(parents=True)
        (root/'_project.md').write_text('---\ndescription: demo\nstatus: building\n---\n')
        reg.invalidate()
        yield root
        reg.invalidate()

def handoff(root, name, body, stamp=1000, meta=''):
    p=root/'handoffs'/name
    p.write_text(f'---\ntype: handoff\nproject: Demo\ntitle: {name}\n{meta}---\n{body}')
    os.utime(p,(stamp,stamp)); reg.invalidate()
    return p

@pytest.mark.parametrize('heading', ['Current state', 'Open issues', 'Next steps'])
@pytest.mark.parametrize('empty', ['', 'none\n', '-\n'])
def test_explicit_empty_clears_snapshot(heading, empty):
    docs=[('old',f'## {heading}\n- stale-marker\n'), ('new',f'## {heading}\n{empty}')]
    result=reg._deterministic_compress(docs)['context']
    assert 'stale-marker' not in result


def test_removed_by_correction_still_declares_snapshot():
    docs=[('old','## Current state\n- stale-marker\n'),
          ('new','## Current state\n- port 5000\n## Corrections\n'
           '- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | AFFECTS: deployment\n')]
    assert 'stale-marker' not in reg._deterministic_compress(docs)['context']


def test_mixed_order_is_chronological(vault):
    handoff(vault,'precise.md','## Current state\n- OLD-marker\n',5000,
            'created_at: 2026-10-01T12:00:00Z\n')
    handoff(vault,'legacy.md','## Current state\n- NEW-marker\n',1,
            'date: 2026-10-02\n')
    reg.generate_context('Demo')
    ctx=reg.context_info('Demo')['context']
    assert 'NEW-marker' in ctx and 'OLD-marker' not in ctx

@pytest.mark.parametrize('field,value', [('title','renamed'), ('created_at','2026-10-08T12:00:00Z'), ('date','2026-10-09')])
def test_metadata_invalidates_context(vault,field,value):
    p=handoff(vault,'one.md','## Current state\n- CURRENT demo works\n')
    reg.generate_context('Demo')
    import frontmatter
    post=frontmatter.load(p); post[field]=value
    p.write_text(frontmatter.dumps(post)); os.utime(p,(1000,1000)); reg.invalidate()
    assert reg.generate_context('Demo')['status']=='generated'
    assert reg.generate_context('Demo')['status']=='fresh'


def test_pipeline_updates_old_mtime_and_no_repeat_ai(vault,monkeypatch):
    handoff(vault,'old.md','## Current state\n- CURRENT old-marker\n## Next steps\n- stale-task\n',9000)
    prompts=[]
    def complete(system,prompt,validator,expected,**kw):
        prompts.append(prompt)
        if 'Runbook' in expected:
            result='# Demo — Runbook\n## Workarounds and gotchas\nnot documented'
        else:
            result='## Overview\nDemo\n## Where it stands\nWorks\n## Pick up here\nnot documented'
        assert validator(result)
        return result
    monkeypatch.setattr(reg,'_complete',complete)
    monkeypatch.setattr(reg,'LOCAL_AI_MAX_SOURCE_DOCS',0)
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    reg.generate_summary('Demo'); reg.generate_runbook('Demo')
    assert len(prompts)==2
    handoff(vault,'new.md','## Current state\n- CURRENT new-marker\n## Next steps\n\n',1,
            'created_at: 2026-10-07T12:00:00Z\n')
    assert reg.correction_propagation_needed('Demo')
    result=reg.refresh_project('Demo')
    assert result['status']=='generated' and len(prompts)==4
    for prompt in prompts[2:]:
        assert 'old-marker' not in prompt and 'stale-task' not in prompt
        assert 'new-marker' in prompt
    assert not reg.correction_propagation_needed('Demo')
    assert reg.refresh_project('Demo')['status']=='fresh'
    assert len(prompts)==4
    assert reg.generate_runbook('Demo')['status']=='fresh'
    # Metadata supplied to prompts also invalidates derived artifacts.
    meta=vault/'_project.md'
    meta.write_text('---\ndescription: changed direction\nstatus: building\n---\n')
    reg.invalidate()
    assert reg.generate_context('Demo')['status']=='fresh'
    assert reg.refresh_project('Demo')['status']=='generated'
    assert len(prompts)==6


def test_failed_ai_does_not_advance_digest(vault,monkeypatch):
    handoff(vault,'one.md','## Current state\n- CURRENT demo works\n')
    def fail(*a,**k): raise RuntimeError('simulated failure')
    monkeypatch.setattr(reg,'_complete',fail)
    assert reg.generate_summary('Demo')['status']=='error'
    assert not reg.summary_info('Demo')['has_summary']
    assert reg.generate_runbook('Demo')['status']=='error'
    assert not reg.runbook_info('Demo')['has_runbook']
