"""Regression checks: favourites are metadata, budget is clearly labelled."""
import sys
from pathlib import Path

import frontmatter
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import register
import app
import checkpoints


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(register, 'VAULT_PATH', tmp_path)
    root = tmp_path / 'projects'
    for name in ('Demo', 'Zebra'):
        path = root / name
        (path / 'handoffs').mkdir(parents=True)
        (path / '_project.md').write_text(
            '---\ndescription: demo\nstatus: building\n---\n', encoding='utf-8')
    register.invalidate()
    yield root
    register.invalidate()


def test_favourite_metadata_and_archive_roundtrip(vault):
    assert register.get_meta('Demo')['favourite'] is False
    assert register.set_favourite('Demo', True)['status'] == 'ok'
    assert register.project('Demo')['favourite'] is True
    meta = frontmatter.load(vault / 'Demo' / '_project.md')
    assert meta['favourite'] is True
    assert meta['description'] == 'demo'
    assert register.set_archived('Demo', True)['status'] == 'ok'
    assert register.project('Demo')['archived'] is True
    assert register.get_meta('Demo')['favourite'] is True
    assert register.set_archived('Demo', False)['status'] == 'ok'
    assert register.project('Demo')['favourite'] is True
    assert register.set_favourite('Demo', False)['status'] == 'ok'
    assert register.project('Demo')['favourite'] is False


def test_favourite_api_validation_and_dashboard_group(vault):
    client = app.app.test_client()
    assert client.post('/api/favourite/Demo', json={'favourite': True}).status_code == 200
    for bad in ('yes', 1, None):
        assert client.post('/api/favourite/Demo', json={'favourite': bad}).status_code == 400
    assert client.post('/api/favourite/DoesNotExist', json={'favourite': True}).status_code == 404
    assert register.get_meta('Demo')['favourite'] is True
    html = client.get('/').get_data(as_text=True)
    assert 'favourites <span class="dim">(1)</span>' in html
    assert 'other projects <span class="dim">(1)</span>' in html
    assert html.index('>Demo</a>') < html.index('>Zebra</a>')
    assert 'data-favourite="1"' in html


def test_detail_budget_and_debrief_ui_cleanup(vault, monkeypatch):
    monkeypatch.setattr(checkpoints, 'HARD_MAX_TOKENS', 30000)
    cpath = vault / 'Demo' / 'Demo_CONTEXT.md'
    cpath.write_text(frontmatter.dumps(frontmatter.Post('CTX/2\nGOAL\n- test',
        type='project-context', estimated_tokens=16000, generated_at='2026-10-17',
        source_mode='conversation-checkpoint')) + '\n', encoding='utf-8')
    register.invalidate()
    client = app.app.test_client()
    html = client.get('/p/Demo').get_data(as_text=True)
    assert '16,000 / 30,000 estimated tokens' in html
    assert 'including its human summary' in html
    assert 'debrief prompt</button>' not in html
    assert 'handoff prompt</button>' in html
    assert client.get('/prompt/debrief?project=Demo').status_code == 200
