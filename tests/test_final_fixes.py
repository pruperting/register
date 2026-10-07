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
