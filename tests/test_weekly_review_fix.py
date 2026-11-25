"""Run against patched Register with pytest tests/test_weekly_review_fix.py.
Also runnable against patch payload with REGISTER_PATCH_PAYLOAD=1 for offline tests.
"""
import os
import sys
import re
import types
from datetime import date
from pathlib import Path
from unittest.mock import Mock
import pytest

if os.environ.get('REGISTER_PATCH_PAYLOAD') == '1':
    from weekly_review_fix import NEW
    s = types.ModuleType('synthesise')
    # Faithful copy of the unchanged CTX parser from the fetched GitHub source.
    s._CTX_SECTIONS = ('GOAL', 'STACK', 'ARCH', 'FILES', 'STATE', 'DONE', 'CORRECTIONS',
                       'DEC', 'INV', 'BUG', 'OPEN', 'NEXT', 'REJECTED', 'FACTS')
    def sections(text):
        heading = '|'.join(map(re.escape, s._CTX_SECTIONS))
        matches = list(re.finditer(rf'(?m)^({heading})\s*$', text or ''))
        out = {name: '' for name in s._CTX_SECTIONS}
        for i, match in enumerate(matches):
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            body = text[match.end():end].strip()
            if body and body != '-':
                name = match.group(1)
                out[name] = (out[name] + '\n' + body).strip() if out[name] else body
        return out
    s.__dict__.update(_ctx_sections=sections, CHAR_BUDGET=700000, PER_PROJECT_CHARS=45000,
                      date=date, Path=Path, re=re, os=os, sys=sys,
                      argparse=__import__('argparse'), DEFAULT_VAULT='/vault',
                      MODEL='gemini-2.5-pro', _redact_for_external_ai=lambda t:(t, {}))
    exec(NEW, s.__dict__)
else:
    import synthesise as s


def record(id='a', ctx='DONE\n- old work', inbox=''):
    return ({'id': id, 'context': ctx, 'created_at': '2026-11-20T10:00:00+00:00'}, inbox, {})


def state(id='a', inbox=''):
    return {'id': id, 'inbox': s._digest(inbox)}


def plan(previous, current, excluded=(), archived=()):
    return s._weekly_plan(Path('/unused'), previous, current, excluded, archived)


def test_first_run_is_baseline():
    m, b, c, u, d, r = plan(None, {'A': record()})
    assert m == {'A': state()} and not b and not c


def test_unchanged_project_not_sent():
    m, b, c, u, d, r = plan({'A': state()}, {'A': record()})
    assert not b and u == ['A'] and m == {'A': state()}


def test_only_changed_sections(monkeypatch):
    monkeypatch.setattr(s, '_prior_context', lambda *a: 'DONE\n- old work\nSTATE\n- running\nOPEN\n- task')
    m, b, c, u, d, r = plan({'A': state(), 'B': state()}, {'A': record('b','DONE\n- old work\n- new work\nSTATE\n- running\nOPEN\n-'), 'B': record()})
    assert c == ['A'] and u == ['B'] and m['A']['id'] == 'b'
    assert 'new work' in b[0] and 'BEFORE:' in b[0] and 'AFTER:' in b[0]
    assert 'STATE\n' not in b[0] and 'OPEN\nBEFORE:' in b[0]


def test_inbox_only_change():
    m, b, c, u, d, r = plan({'A': state()}, {'A': record(inbox='new task')})
    assert 'Checkpoint unchanged' in b[0] and 'new task' in b[0]
    assert m['A'] == state(inbox='new task')


def test_unavailable_old_checkpoint(monkeypatch):
    monkeypatch.setattr(s, '_prior_context', lambda *a: None)
    m,b,*_ = plan({'A':state()}, {'A':record('b')})
    assert 'no reliable delta' in b[0]


def test_new_project_not_assumed_new_work():
    m,b,*_ = plan({}, {'A':record()})
    assert 'historical context' in b[0]


def test_exclusions_and_archives():
    m,b,c,u,d,r = plan({'A':state(),'B':state(),'C':state()}, {}, ['A'], ['B'])
    assert 'A' in m and 'B' not in m and 'C' in m and r == ['B','C']


def test_budget_preserves_baseline(monkeypatch):
    monkeypatch.setattr(s,'CHAR_BUDGET',24001)
    m,b,c,u,d,r = plan({}, {'A':record()})
    assert not b and not m and d == ['A']


def test_larger_than_old_per_project_limit(monkeypatch):
    monkeypatch.setattr(s,'PER_PROJECT_CHARS',10)
    m,b,c,u,d,r = plan({}, {'A':record()})
    assert b and not d


def write_review(root, day, model='gemini-2.5-pro', body='review', manifest=True):
    content = '---\ngenerated_by: '+model+'\n'
    if manifest:
        content += 'weekly_manifest: '+s.json.dumps({'version':1,'projects':{'A':state()}})+'\n'
    (root/f'review-{day}.md').write_text(content+'---\n'+body)


def test_legacy_review_has_no_baseline(tmp_path):
    write_review(tmp_path,'2026-11-22',manifest=False)
    assert s._previous_week(tmp_path,date(2026,11,29)) == (None,'','2026-11-22')


def test_quiet_week_retains_continuity(tmp_path):
    write_review(tmp_path,'2026-11-15',body='substantive advice')
    write_review(tmp_path,'2026-11-22',model='deterministic',body='quiet')
    write_review(tmp_path,'2026-11-29',body='same day excluded')
    m,body,day=s._previous_week(tmp_path,date(2026,11,29))
    assert m=={'A':state()} and body=='substantive advice' and day=='2026-11-22'


def test_invalid_manifest_fails_closed(tmp_path):
    (tmp_path/'review-2026-11-22.md').write_text('---\nweekly_manifest: {}\n---\nreview')
    with pytest.raises(ValueError): s._previous_week(tmp_path,date(2026,11,29))


def test_output_validation():
    body='\n'.join('## '+h+'\nNone evidenced' for h in s.WEEKLY_SECTIONS)
    response=types.SimpleNamespace(candidates=[types.SimpleNamespace(finish_reason='STOP')],text=body)
    assert s._weekly_text(response)==body
    response.candidates[0].finish_reason='MAX_TOKENS'
    with pytest.raises(ValueError): s._weekly_text(response)
    response.candidates[0].finish_reason='STOP'
    response.text='## What changed\npartial'
    with pytest.raises(ValueError): s._weekly_text(response)


def test_baseline_and_quiet_main_no_api(tmp_path, monkeypatch):
    (tmp_path/'projects').mkdir()
    monkeypatch.setattr(s,'_weekly_inventory',lambda v:({'A':record()},[],[]))
    monkeypatch.setattr(sys,'argv',['synthesise.py','--vault',str(tmp_path)])
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    reg=types.SimpleNamespace(_atomic_write=lambda p,t:p.write_text(t))
    monkeypatch.setitem(sys.modules,'register',reg)
    class FakeDate(date):
        @classmethod
        def today(cls): return cls(2026,11,29)
    monkeypatch.setattr(s,'date',FakeDate)
    s.main()
    path=tmp_path/'projects'/'_estate'/'review-2026-11-29.md'
    assert 'Baseline only' in path.read_text()
    old=path.read_text()
    s.main()
    assert path.read_text()==old
    class NextDate(date):
        @classmethod
        def today(cls): return cls(2026,12,6)
    monkeypatch.setattr(s,'date',NextDate)
    s.main()
    assert 'No Gemini call made' in (path.parent/'review-2026-12-06.md').read_text()
