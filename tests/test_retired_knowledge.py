"""Historical handoff integration tests. Run with python -m pytest -q tests/."""
from __future__ import annotations

import sys
from pathlib import Path
import os

import frontmatter
import pytest

os.environ['AUTO_SUMMARY'] = 'false'
os.environ['MONTHLY_SYNTHESIS'] = 'false'
os.environ['HERALD_STATUS_EXPORT'] = 'false'

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import checkpoints as cp
import register as reg
import retired_knowledge as rk


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, 'VAULT_PATH', tmp_path)
    root = tmp_path / 'projects' / 'Demo'
    (root / 'handoffs').mkdir(parents=True)
    (root / '_project.md').write_text('---\ndescription: Demo\nstatus: building\n---\n')
    reg.invalidate()
    yield root
    reg.invalidate()


def _ctx(section='FACTS', item='- Historical fact that should not be current.'):
    return 'CTX/2\n' + '\n'.join(s + '\n' + (item if s == section else '-') for s in cp.SECTIONS)


def _main(root, parent='ROOT', stamp='2026-10-16T21:00:00Z', sidecar=True):
    ctx = _ctx('STATE', '- CURRENT application is running on port 5557.')
    meta = {'type': 'handoff', 'project': 'Demo', 'title': 'new handoff',
            'checkpoint_version': 1, 'based_on': parent, 'created_at': stamp}
    if sidecar:
        meta['retired_sidecar'] = True
    body = '## Human summary\nDemo is running.\n\n## AI checkpoint\n' + ctx
    (root / 'handoffs' / 'new.md').write_text(frontmatter.dumps(frontmatter.Post(body, **meta)))
    reg.invalidate()
    return cp.parse(meta, body, 'Demo')['id']


def _retired(root, old='ROOT', stamp='2026-10-16T21:00:00Z',
             filename='retired.md', note='- Old deployment used port 5000; corrected.'):
    meta = {'type': 'retired-knowledge', 'archive_version': 1, 'project': 'Demo',
            'retired_from': old, 'paired_created_at': stamp,
            'title': 'retired lessons'}
    path = root / 'handoffs' / filename
    path.write_text(frontmatter.dumps(frontmatter.Post(_ctx('CORRECTIONS', note), **meta)))
    reg.invalidate()
    return path


def test_pair_required_before_active_import(demo):
    _main(demo)
    result = reg.refresh_project('Demo')
    assert result['status'] == 'error'
    assert 'retired' in result['reason'].lower()
    _retired(demo)
    result = reg.refresh_project('Demo')
    assert result['status'] == 'generated', result
    assert 'CURRENT application' in reg.context_info('Demo')['context']


def test_retired_material_excluded_from_live_views_and_prompt(demo):
    _main(demo)
    _retired(demo, note='- SUPERSEDED_SECRETLESS_MARKER; do not use this obsolete setup.')
    assert reg.refresh_project('Demo')['status'] == 'generated'
    p = reg.project('Demo')
    assert p['handoff_count'] == 1
    assert p['reference_count'] == 0
    current = reg.context_info('Demo')['context']
    assert 'SUPERSEDED_SECRETLESS_MARKER' not in current
    assert 'SUPERSEDED_SECRETLESS_MARKER' not in app._prompt_text('handoff', 'Demo')
    archived = rk.export('Demo')
    assert 'SUPERSEDED_SECRETLESS_MARKER' in archived
    assert archived.index('CORRECTIONS\n') > archived.index('DONE\n')


def test_historical_export_download_is_explicit(demo):
    _main(demo)
    _retired(demo)
    reg.refresh_project('Demo')
    result = app.app.test_client().get('/api/retired/Demo?download=1')
    assert result.status_code == 200
    assert b'Old deployment used port 5000' in result.data
    assert 'attachment' in result.headers['Content-Disposition']
    page = app.app.test_client().get('/p/Demo').get_data(as_text=True)
    assert 'download historical' in page


def test_repeated_import_is_idempotent_and_duplicate_copy_is_harmless(demo):
    _main(demo)
    original = _retired(demo)
    assert reg.refresh_project('Demo')['status'] == 'generated'
    before = rk.archive_path('Demo').read_bytes()
    (original.parent / 'synced-copy.md').write_bytes(original.read_bytes())
    reg.invalidate()
    assert reg.refresh_project('Demo')['status'] == 'fresh'
    assert rk.sync('Demo')['status'] == 'fresh'
    assert rk.archive_path('Demo').read_bytes() == before
    assert frontmatter.load(rk.archive_path('Demo'))['source_count'] == 1


def test_mismatched_parent_or_timestamp_does_not_allow_publish(demo):
    _main(demo)
    _retired(demo, old='a' * 64)
    result = reg.refresh_project('Demo')
    assert result['status'] == 'error'
    assert 'matching' in result['reason'].lower()


def test_archive_conflict_does_not_silently_overwrite(demo):
    _main(demo)
    _retired(demo)
    assert reg.refresh_project('Demo')['status'] == 'generated'
    old = rk.archive_path('Demo').read_bytes()
    _retired(demo, filename='other.md', note='- Different historical claim, same pair.')
    result = reg.refresh_project('Demo')
    assert result['status'] == 'error'
    assert rk.archive_path('Demo').read_bytes() == old


def test_archive_can_arrive_first_without_corrupting_current_state(demo):
    _retired(demo)
    assert reg.project('Demo')['handoff_count'] == 0
    assert rk.sync('Demo')['status'] == 'pending'
    _main(demo)
    assert reg.refresh_project('Demo')['status'] == 'generated'
    assert 'Old deployment' in rk.export('Demo')


def test_bad_archive_is_not_silently_accepted(demo):
    _main(demo)
    path = _retired(demo)
    path.write_text(path.read_text().replace('CORRECTIONS\n', 'REMOVED\n'))
    reg.invalidate()
    result = reg.refresh_project('Demo')
    assert result['status'] == 'error'
    assert 'section' in result['reason'].lower()


def test_missing_historical_evidence_does_not_shrink_archive(demo):
    _main(demo)
    source = _retired(demo)
    assert reg.refresh_project('Demo')['status'] == 'generated'
    previous = rk.archive_path('Demo').read_bytes()
    source.unlink()
    reg.invalidate()
    report = rk.sync('Demo')
    assert report['status'] == 'error'
    assert rk.archive_path('Demo').read_bytes() == previous
    # Recovery remains available even while the source needs repair.
    assert 'Old deployment used port 5000' in rk.export('Demo')
