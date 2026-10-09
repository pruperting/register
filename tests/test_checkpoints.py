"""Integration contracts for conversation-authored snapshots and explicit AI use."""
import io
import json
import os
import sys
from pathlib import Path
import subprocess
from datetime import datetime, timezone

import frontmatter
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import register as reg
import checkpoints as cp
import app
import synthesise
import herald_status

cp_test_complete = reg._complete


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, 'VAULT_PATH', tmp_path)
    root = tmp_path/'projects'/'Demo'; (root/'handoffs').mkdir(parents=True)
    (root/'_project.md').write_text('---\ndescription: demo\nstatus: building\n---\n')
    reg.invalidate()
    monkeypatch.setattr(reg, '_complete', lambda *a, **k: pytest.fail('unexpected AI generation'))
    yield root
    reg.invalidate()


def body(state='CURRENT app.py works.', opens='- TODO T-2: investigate cache.', nexts='- TODO T-3: deploy.', done='- DONE T-1: fix parser.'):
    values = {'GOAL': '- Keep Demo useful.', 'STACK': '- Docker, port 5557.',
              'ARCH': '- Flask and synced vault.', 'FILES': '- app.py and music_library.db.',
              'STATE': '- '+state, 'DONE': done,
              'CORRECTIONS': '- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5557 | AFFECTS: deployment | EVIDENCE: runtime',
              'DEC': '- Use immutable checkpoints.', 'INV': '- Never infer completion from silence.',
              'BUG': '- Preserve the exact error ModuleNotFoundError.', 'OPEN': opens,
              'NEXT': nexts, 'REJECTED': '- REJECTED old queue.', 'FACTS': '- host /srv/demo.'}
    return '## Human summary\nDemo is running; deploy next.\n\n## AI checkpoint\nCTX/2\n' + '\n'.join(s+'\n'+values.get(s,'-') for s in cp.SECTIONS)


def snapshot(root, filename='one.md', parent=None, content=None, mtime=1, **extra):
    reg.invalidate()
    if parent is None:
        parent = cp.identity('Demo')
    meta = {'type': 'handoff', 'project': 'Demo', 'title': filename,
            'checkpoint_version': 1, 'based_on': parent,
            'created_at': '2026-10-07T12:00:00Z', **extra}
    content = content or body()
    path = root/'handoffs'/filename
    path.write_text(frontmatter.dumps(frontmatter.Post(content, **meta)))
    os.utime(path,(mtime,mtime)); reg.invalidate()
    return cp.parse(meta, content, 'Demo')['id']


def legacy(root):
    path=root/'handoffs'/'legacy.md'
    path.write_text('---\ntype: handoff\nproject: Demo\n---\n## Current state\n- CURRENT stale fact.\n## Open issues\n- Old task.\n')
    reg.invalidate()
    return path


def test_import_exact_complete_pair_and_no_ai(project):
    source=body(); key=snapshot(project, content=source)
    assert reg.refresh_project('Demo')['status']=='generated'
    assert cp.identity('Demo') == key
    assert reg.context_info('Demo')['context'] == source.split('## AI checkpoint\n')[1].strip()
    assert reg.summary_info('Demo')['summary']=='Demo is running; deploy next.'
    for _ in range(3):
        assert reg.refresh_project('Demo')['status']=='fresh'
        assert reg.generate_summary('Demo',full=True)['status']=='fresh'
        assert reg.generate_context('Demo',full=True)['status']=='fresh'
    assert not (project/'Demo_RUNBOOK.md').exists()


def test_chain_replaces_all_sections_even_empty_with_preserved_mtimes(project):
    key=snapshot(project,mtime=9000); reg.refresh_project('Demo')
    snapshot(project,'two.md',parent=key,content=body(state='CURRENT new value.',opens='-',nexts='-',done='- DONE T-2: investigation.'),mtime=1)
    assert reg.refresh_project('Demo')['status']=='generated'
    context=reg.context_info('Demo')['context']
    assert 'new value' in context and 'app.py works' not in context
    assert cp.split_context(context)['OPEN']=='-'
    assert cp.split_context(context)['NEXT']=='-'
    assert 'DONE T-2' in context and 'DONE T-1' not in context


def test_chain_order_does_not_depend_on_timestamps(project):
    first=snapshot(project,'one.md',mtime=9000)
    second=snapshot(project,'two.md',parent=first,content=body(state='CURRENT second.'),mtime=1,created_at='2020-01-01T00:00:00Z')
    assert cp.identity('Demo')==second
    assert reg.refresh_project('Demo')['status']=='generated'


def test_duplicate_synced_copy_is_idempotent(project):
    snapshot(project); reg.refresh_project('Demo')
    (project/'handoffs'/'duplicate.md').write_bytes((project/'handoffs'/'one.md').read_bytes())
    reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='fresh'


@pytest.mark.parametrize('broken', ['missing', 'duplicate', 'reordered', 'blank', 'wrong-version', 'missing-parent', 'bad-time', 'unclosed-fence', 'oversize'])
def test_invalid_snapshot_retains_both_published_views(project,broken):
    key=snapshot(project); reg.refresh_project('Demo')
    context=(project/'Demo_CONTEXT.md').read_bytes(); summary=(project/'Demo_summary.md').read_bytes()
    meta={'type':'handoff','project':'Demo','checkpoint_version':1,'based_on':key,'created_at':'2026-10-08T00:00:00Z'}
    value=body(state='CURRENT new value.')
    if broken=='missing': value=value.replace('DONE\n- DONE T-1: fix parser.\n','')
    if broken=='duplicate': value += '\nDONE\n- duplicate'
    if broken=='reordered': value=value.replace('GOAL\n','TEMP\n').replace('STACK\n','GOAL\n').replace('TEMP\n','STACK\n')
    if broken=='blank': value=value.replace('OPEN\n- TODO T-2: investigate cache.','OPEN\n')
    if broken=='wrong-version': meta['checkpoint_version']=2
    if broken=='missing-parent': meta.pop('based_on')
    if broken=='wrong-project': meta['project']='demo'
    if broken=='bad-time': meta['created_at']='2026-10-08'
    if broken=='unclosed-fence': value += '\n```bash\nunfinished'
    if broken=='oversize': value+='x'*61000
    (project/'handoffs'/'broken.md').write_text(frontmatter.dumps(frontmatter.Post(value,**meta)))
    reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='error'
    assert (project/'Demo_CONTEXT.md').read_bytes()==context
    assert (project/'Demo_summary.md').read_bytes()==summary


def test_conflicting_siblings_and_missing_ancestor_never_win_by_mtime(project):
    root=snapshot(project); reg.refresh_project('Demo')
    snapshot(project,'a.md',parent=root,content=body(state='CURRENT branch A.'),mtime=9000)
    snapshot(project,'b.md',parent=root,content=body(state='CURRENT branch B.'),mtime=1)
    assert 'conflicting' in reg.refresh_project('Demo')['reason']
    (project/'handoffs'/'b.md').unlink(); reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='generated'
    (project/'handoffs'/'one.md').unlink(); reg.invalidate()
    assert 'ancestry' in reg.refresh_project('Demo')['reason']


def test_existing_legacy_baseline_migrates_without_unioning_old_tasks(project):
    old=legacy(project)
    parent=cp.identity('Demo'); assert parent.startswith('legacy:')
    snapshot(project,parent=parent,content=body(opens='-',nexts='-'))
    assert reg.refresh_project('Demo')['status']=='generated'
    assert 'Old task' not in reg.context_info('Demo')['context']
    # Never silently ignore a later incremental handoff after the full snapshot.
    legacy_path=project/'handoffs'/'late.md'
    legacy_path.write_text('---\ntype: handoff\nproject: Demo\n---\n## Current state\n- Extra change')
    reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='error'
    assert old.exists()


def test_bootstrap_required_never_calls_ai(project):
    legacy(project)
    assert reg.refresh_project('Demo')['status']=='bootstrap-required'
    assert reg.generate_summary('Demo')['status']=='bootstrap-required'
    assert reg.generate_runbook('Demo')['ai_calls']==0
    assert reg.generate_context('Demo')['migration_required']


def test_explicit_gemini_bootstrap_redacts_and_only_runs_once(project,monkeypatch):
    legacy(project)
    old=project/'handoffs'/'legacy.md'
    old.write_text(old.read_text()+'\nAPI key AIza'+'S'*32+'\n')
    reg.invalidate(); monkeypatch.setenv('GEMINI_API_KEY','test-key')
    calls=[]
    def complete(system,prompt,validator,expected,**kwargs):
        calls.append((prompt,kwargs))
        assert 'AIza'+'S'*32 not in prompt
        value=body().replace('host /srv/demo.', 'host /srv/demo. AIza'+'Z'*32)
        assert validator(value)
        return value
    monkeypatch.setattr(reg,'_complete',complete)
    result=reg.consolidate_handoffs('Demo')
    assert result['status']=='generated' and result['ai_calls']==1
    assert calls[0][1]['backend']=='gemini'
    assert calls[0][1]['retry'] is False
    assert '[REDACTED GOOGLE API KEY]' in reg.context_info('Demo')['context']
    assert reg.consolidate_handoffs('Demo')['status']=='fresh'
    assert len(calls)==1
    assert 'AIza'+'S'*32 in old.read_text()  # evidence immutable


def test_bootstrap_missing_key_and_bad_output_create_no_checkpoint(project,monkeypatch):
    legacy(project); monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    assert 'GEMINI_API_KEY' in reg.consolidate_handoffs('Demo')['reason']
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(reg,'_complete',lambda *a,**k:'## Human summary\nBroken')
    assert reg.consolidate_handoffs('Demo')['status']=='error'
    assert len(list((project/'handoffs').glob('*.md')))==1


def test_bootstrap_ignores_echoed_ancestry_but_preserves_all_evidence(project, monkeypatch):
    legacy(project); monkeypatch.setenv('GEMINI_API_KEY', 'test')
    parent = cp.identity('Demo')
    original = body().replace('host /srv/demo.', 'Project: Demo\nPrior checkpoint ID: technical literal inside FACTS')
    echoed = original.replace('CTX/2\n', 'CTX/2\nProject: Demo\nPrior checkpoint ID: legacy:incorrect-model-echo\n', 1)
    def complete(system, prompt, validator, expected, **kwargs):
        assert validator(echoed)
        return echoed
    monkeypatch.setattr(reg, '_complete', complete)
    result = reg.consolidate_handoffs('Demo')
    assert result['status'] == 'generated' and result['ai_calls'] == 1
    meta, saved = reg._read(reg.VAULT_PATH / result['path'])
    assert meta['based_on'] == parent
    assert saved == original
    # Conversation-authored checkpoints still require the exact strict format.
    with pytest.raises(ValueError, match='unexpected text'):
        cp.split_context(echoed.split('## AI checkpoint\n')[1])


@pytest.mark.parametrize('preamble', ['Project: Other', 'Unclassified evidence must survive'])
def test_bootstrap_preamble_does_not_hide_wrong_project_or_arbitrary_text(project, monkeypatch, preamble):
    legacy(project); monkeypatch.setenv('GEMINI_API_KEY', 'test')
    value = body().replace('CTX/2\n', 'CTX/2\n' + preamble + '\n', 1)
    def complete(system, prompt, validator, expected, **kwargs):
        assert not validator(value)
        raise RuntimeError('invalid output')
    monkeypatch.setattr(reg, '_complete', complete)
    result = reg.consolidate_handoffs('Demo')
    assert result['status'] == 'error'
    assert len(list((project / 'handoffs').glob('*.md'))) == 1


def test_rejected_gemini_output_has_precise_redacted_diagnostics(project,monkeypatch):
    from types import SimpleNamespace
    from google import genai
    legacy(project); monkeypatch.setenv('GEMINI_API_KEY','test')
    secret = 'AIza' + 'S'*32
    raw = '## Human summary\nCurrent app\n## AI checkpoint\nCTX/2\nGOAL\n' + secret
    response = SimpleNamespace(text=raw,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(value='MAX_TOKENS'))],
        usage_metadata=SimpleNamespace(prompt_token_count=1200,candidates_token_count=500,thoughts_token_count=300))
    calls = []
    def generate(**kwargs):
        calls.append(kwargs); return response
    monkeypatch.setattr(genai,'Client',lambda **kw: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(reg,'_complete',cp_test_complete)
    result = reg.consolidate_handoffs('Demo')
    assert result['status']=='error' and len(calls)==1
    assert 'truncated the checkpoint' in result['reason']
    assert 'MAX_TOKENS' in result['reason']
    diagnostic = json.loads((reg.VAULT_PATH/result['diagnostic_path']).read_text())
    assert secret not in json.dumps(diagnostic)
    assert '[REDACTED GOOGLE API KEY]' in diagnostic['raw_output']
    assert diagnostic['candidates_token_count']==500
    assert diagnostic['thoughts_token_count']==300
    assert diagnostic['estimated_tokens']==reg._estimate_tokens(raw)
    assert len(list((project/'handoffs').glob('*.md')))==1
    assert reg.refresh_project('Demo')['status']=='bootstrap-required'


def test_bootstrap_budget_rejection_is_distinct_from_format_failure(project,monkeypatch):
    legacy(project); monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(cp,'_bootstrap_budget',lambda *a:dict(target_tokens=5,ceiling_tokens=10,generation_tokens=100))
    def complete(system,prompt,validator,expected,**kwargs):
        assert not validator(body())
        raise RuntimeError('generic failure')
    monkeypatch.setattr(reg,'_complete',complete)
    result = reg.consolidate_handoffs('Demo')
    assert 'output exceeds bootstrap ceiling' in result['reason']
    assert 'generic failure' not in result['reason']
    assert len(list((project/'handoffs').glob('*.md')))==1


@pytest.mark.parametrize('evidence,ceiling,generation',[(1000,5000,7500),(12253,15000,22500),(100000,15000,22500)])
def test_complete_checkpoint_budget_scales_without_exceeding_artifact_cap(evidence,ceiling,generation):
    budget=cp._bootstrap_budget(evidence,2)
    assert budget['ceiling_tokens']==ceiling
    assert budget['generation_tokens']==generation
    assert budget['target_tokens']==reg._consolidation_budget(evidence,2)['target_tokens']


@pytest.mark.parametrize('state_size,accepted',[(31000,True),(61000,False)])
def test_large_bootstrap_accepts_complete_output_but_keeps_15000_cap(project,monkeypatch,state_size,accepted):
    legacy(project);monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(reg,'GEMINI_MODEL','gemini-2.5-flash')
    monkeypatch.setattr(reg,'_batch_project_material',lambda *a:('x'*49012,['batch']))
    calls=[]
    def complete(system,prompt,validator,expected,**kwargs):
        calls.append(kwargs)
        assert kwargs['max_output_tokens']==24548
        assert 'hard maximum 15000' in prompt
        value=body(state='x'*state_size)
        assert validator(value)==accepted
        if not accepted:raise RuntimeError('invalid output')
        return value
    monkeypatch.setattr(reg,'_complete',complete)
    result=reg.consolidate_handoffs('Demo')
    assert len(calls)==1
    if accepted:
        assert result['status']=='generated'
        assert reg.context_info('Demo')['context'].count('x')>=state_size
        assert reg.refresh_project('Demo')['status']=='fresh'
    else:
        assert result['status']=='error' and '15000' in result['reason']
        assert len(list((project/'handoffs').glob('*.md')))==1


@pytest.mark.parametrize('model,reasoning', [('gemini-2.5-flash',2048), ('models/gemini-2.5-pro',2048), ('gemini-2.0-flash',None)])
@pytest.mark.parametrize('finish', ['STOP','MAX_TOKENS'])
def test_bootstrap_reserves_reasoning_and_rejects_even_structured_truncation(project,monkeypatch,model,reasoning,finish):
    from types import SimpleNamespace
    from google import genai
    from google.genai import types
    legacy(project); monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(reg,'GEMINI_MODEL',model)
    monkeypatch.setattr(cp,'_bootstrap_budget',lambda *a:dict(target_tokens=3000,ceiling_tokens=5000,generation_tokens=6000))
    calls=[]
    response=types.GenerateContentResponse(
        candidates=[types.Candidate(finish_reason=finish,
            content=types.Content(parts=[types.Part(text=body())]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200,candidates_token_count=200,thoughts_token_count=reasoning or 0))
    def generate(**kwargs):
        calls.append(kwargs);return response
    monkeypatch.setattr(genai,'Client',lambda **kw:SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(reg,'_complete',cp_test_complete)
    result=reg.consolidate_handoffs('Demo')
    assert len(calls)==1
    config=calls[0]['config']
    assert config.max_output_tokens==6000+(reasoning or 0)
    if reasoning is None:
        assert config.thinking_config is None
    else:
        assert config.thinking_config.thinking_budget==reasoning
        assert config.model_dump(by_alias=True)['thinkingConfig']['thinkingBudget']==reasoning
    if finish=='MAX_TOKENS':
        assert result['status']=='error' and 'truncated' in result['reason']
        assert len(list((project/'handoffs').glob('*.md')))==1
        assert reg.refresh_project('Demo')['status']=='bootstrap-required'
    else:
        assert result['status']=='generated'
        assert reg.refresh_project('Demo')['status']=='fresh'


def test_concurrent_source_change_during_bootstrap_is_rejected(project,monkeypatch):
    old=legacy(project); monkeypatch.setenv('GEMINI_API_KEY','test')
    def complete(*a,**k):
        old.write_text(old.read_text()+'\nNEW fact'); return body()
    monkeypatch.setattr(reg,'_complete',complete)
    assert 'changed during bootstrap' in reg.consolidate_handoffs('Demo')['reason']
    assert len(list((project/'handoffs').glob('*.md')))==1


def test_explicit_reference_bootstrap_requires_no_handoffs(project,monkeypatch):
    ref=project/'notes.md';ref.write_text('---\nproject: Demo\n---\nCurrent app.py configuration')
    reg.invalidate(); monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(reg,'_complete',lambda *a,**k:body())
    assert reg.bootstrap_handoff('Demo')['status']=='generated'
    assert ref.exists()
    assert reg.refresh_project('Demo')['status']=='fresh'


def test_legacy_bootstrap_compression_preserves_old_tasks_and_literals(project):
    docs=[('old','## Open issues\n- Outstanding original task\n## Code\n```bash\ndocker compose up -d\n```'),
          ('new','## Open issues\n- New blocker')]
    text,_=reg._batch_project_material('Demo',docs)
    assert 'Outstanding original task' in text and 'New blocker' in text
    assert 'docker compose up -d' in text


def test_compact_export_preserves_all_tracking_and_code_and_source(project):
    value=body().replace('- host /srv/demo.', '```bash\nprintf "OPEN\\n"\n```\n- host /srv/demo.')
    snapshot(project,content=value); reg.refresh_project('Demo')
    source=(project/'handoffs'/'one.md').read_bytes()
    before=reg.context_info('Demo')['context']
    compact=cp.export_context('Demo',compact=True)
    assert compact.startswith('CHECKPOINT_ID ')
    sections=cp.split_context(compact.split('\n',1)[1])
    for section in cp.SECTIONS:
        for line in cp.split_context(before)[section].splitlines():
            assert line in sections[section]
    assert (project/'handoffs'/'one.md').read_bytes()==source
    assert reg.context_info('Demo')['context']==before


def test_checkpoint_parser_does_not_treat_code_lines_as_headings(project):
    value=body().replace('- host /srv/demo.', '```text\nSTATE\nDONE\nOPEN\n```')
    snapshot(project,content=value)
    assert reg.refresh_project('Demo')['status']=='generated'
    assert cp.split_context(reg.context_info('Demo')['context'])['FACTS'].startswith('```')


def test_upload_compressor_retains_ctx_tracking_sections(project):
    result=reg.compress_documents([('ctx.md',body().split('## AI checkpoint\n')[1])],target_tokens=12000)
    assert result['ai_calls']==0 and result['protected_missing']==0
    assert '- DONE T-1' in result['context']
    assert '- TODO T-2' in result['context'] and '- TODO T-3' in result['context']
    assert 'CORRECTION | PREVIOUS' in result['context']


def test_ui_import_download_prompt_and_retired_runbook(project):
    key=snapshot(project)
    client=app.app.test_client()
    response=client.get('/p/Demo')
    assert response.status_code==200
    page=response.get_data(as_text=True)
    assert 'Demo is running; deploy next.' in page
    assert 'download compact chat copy' in page and 'rb-btn' not in page
    prompt=client.get('/prompt?project=Demo').get_data(as_text=True)
    assert 'based_on: '+key in prompt
    assert 'checkpoint_version: 1' in prompt
    assert 'FILES\n- app.py' in prompt and 'DONE\n- DONE T-1' in prompt
    response=client.get('/api/context/Demo?download=1&compact=1')
    assert response.status_code==200 and 'attachment;' in response.headers['Content-Disposition']
    assert response.get_data(as_text=True).startswith('CHECKPOINT_ID '+key)
    assert client.post('/api/runbook/Demo').status_code==410
    assert client.post('/api/refresh').json['checkpoints']['Demo']['status']=='fresh'


def test_pending_herald_and_weekly_review_use_accepted_snapshot_only(project):
    legacy(project); snapshot(project)
    assert herald_status._project_payload(reg.project('Demo'))['derived_state_pending']
    reg.refresh_project('Demo')
    assert not herald_status._project_payload(reg.project('Demo'))['derived_state_pending']
    estate=project.parent/'_estate';estate.mkdir()
    text,included=synthesise.collect(reg.VAULT_PATH)
    assert included==['Demo'] and 'DONE T-1' in text
    assert 'stale fact' not in text and 'Old task' not in text
    assert 'NEW-HANDOFF DELTA' not in text


@pytest.mark.parametrize('fence',['```','~~~'])
def test_herald_tasks_ignore_code_labels_and_code_bullets(project,fence):
    opens=f'- Investigate cache.\n{fence}\nNEXT\n- This is code, not a task.\n{fence}\n- Investigate worker.'
    value=body(opens=opens)
    snapshot(project,content=value);reg.refresh_project('Demo')
    payload=herald_status._project_payload(reg.project('Demo'))
    assert payload['open']==['Investigate cache.','Investigate worker.']
    assert payload['next']==['TODO T-3: deploy.']


def test_herald_export_baseline_state_changes_new_tasks_and_archival(project,monkeypatch):
    monkeypatch.setattr(herald_status,'ESTATE_DIR',project.parent/'_estate')
    # Preserved Syncthing timestamps and second-resolution JSON times must not
    # hide a new accepted checkpoint whose changes are outside OPEN/NEXT.
    monkeypatch.setattr(herald_status,'_iso',lambda ts:'2026-10-09T20:00:00Z' if ts else None)
    snapshot(project);reg.refresh_project('Demo')
    output=project.parent/'_estate'/'test-herald-status.json'
    first=herald_status.export_status(output)
    assert first['baseline'] and not first['changes']['new_open']
    second=herald_status.export_status(output)
    assert not second['baseline'] and not second['changes']['projects']
    snapshot(project,'two.md',content=body(state='CURRENT worker fixed.'))
    reg.refresh_project('Demo')
    third=herald_status.export_status(output)
    assert third['changes']['projects']==['Demo']
    assert not third['changes']['new_open']
    assert third['projects'][0]['checkpoint_id']!=second['projects'][0]['checkpoint_id']
    snapshot(project,'three.md',content=body(opens='- TODO T-2: investigate cache.\n- TODO T-4: inspect logs.'))
    reg.refresh_project('Demo')
    fourth=herald_status.export_status(output)
    assert [x['item'] for x in fourth['changes']['new_open']]==['TODO T-4: inspect logs.']
    assert herald_status._item_id('Demo',' Todo   T-4: inspect logs. ')==fourth['changes']['new_open'][0]['id']
    assert not fourth['counts']['pending_derived_state']
    reg.set_archived('Demo',True)
    archived=herald_status.export_status(output)
    assert not archived['projects']


@pytest.mark.parametrize('finish,kind', [('STOP','complete'),('MAX_TOKENS','complete'),('STOP','missing'),('STOP','empty')])
def test_weekly_review_cli_validates_before_replacing_and_redacts(project,monkeypatch,finish,kind):
    from types import SimpleNamespace
    from google import genai
    from google.genai import types
    secret='AIza'+'S'*32
    text='\n\n'.join('## '+s+'\n'+('Review '+secret if i==0 else 'Evidence-based observation.')
                         for i,s in enumerate(synthesise.REVIEW_SECTIONS))
    if kind=='missing':text=text.split('## Do these three things next')[0]
    if kind=='empty':text=text.split('## Do these three things next')[0]+'## Do these three things next\n'
    monkeypatch.setattr(synthesise,'collect',lambda vault:('Accepted checkpoint '+secret,['Demo']))
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(sys,'argv',['synthesise.py','--vault',str(reg.VAULT_PATH)])
    response=types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=finish,
        content=types.Content(parts=[types.Part(text=text)]))])
    calls=[]
    def generate(**kwargs):
        assert secret not in kwargs['contents']
        calls.append(kwargs);return response
    monkeypatch.setattr(genai,'Client',lambda **kw:SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    out=project.parent/'_estate'/('review-'+synthesise.date.today().isoformat()+'.md')
    out.parent.mkdir();out.write_text('PREVIOUS VALID REVIEW')
    if finish=='STOP' and kind=='complete':
        synthesise.main()
        saved=out.read_text()
        assert 'projects_reviewed: 1' in saved and secret not in saved
        assert '[REDACTED GOOGLE API KEY]' in saved
        assert all('## '+s in saved for s in synthesise.REVIEW_SECTIONS)
        assert not out.with_name(out.name+'.tmp').exists()
        monkeypatch.setattr(herald_status,'ESTATE_DIR',out.parent)
        payload=herald_status.build_payload()
        assert payload['portfolio_review']['file']==out.name
        assert payload['portfolio_review']['age_days']==0
    else:
        with pytest.raises(SystemExit):synthesise.main()
        assert out.read_text()=='PREVIOUS VALID REVIEW'
    assert len(calls)==1


def test_weekly_review_dry_run_excludes_unseeded_archived_and_estate(project,monkeypatch,capsys):
    snapshot(project)
    for slug in ('Unseeded','Archived','_estate'):
        root=project.parent/slug;root.mkdir()
        (root/'_project.md').write_text('---\ndescription: excluded\n---\n')
    reg.set_archived('Archived',True)
    monkeypatch.setattr(sys,'argv',['synthesise.py','--vault',str(reg.VAULT_PATH),'--dry-run'])
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    with pytest.raises(SystemExit) as stop:synthesise.main()
    assert stop.value.code==0
    output=capsys.readouterr()
    assert output.out.strip()=='Demo'
    assert 'Unseeded' in output.err and '1 projects' in output.err


def test_compression_reports_protected_overflow_without_dropping_tasks(project):
    tasks='\n'.join(f'- TODO T-{i}: preserve /srv/demo/item-{i} and investigate '+('details '*30) for i in range(30))
    result=reg._deterministic_compress([('ctx.md','CTX/2\nOPEN\n'+tasks)],target_tokens=700)
    assert result['protected_tokens']>result['soft_target']
    assert result['budget_overflow']==result['output_tokens']-result['soft_target']
    assert result['overflow_reason']=='protected-facts' and not result['missing_hard']
    assert all(f'TODO T-{i}:' in result['context'] for i in range(30))


def test_scheduled_refresh_no_ai_and_weekly_sunday_trigger(project):
    snapshot(project)
    app.scheduled_refresh()
    assert reg.context_info('Demo')['has_context']
    script='import app; print(app._sched.get_job("weekly_synthesis").trigger); app._sched.shutdown(wait=False)'
    env={**os.environ,'AUTO_SUMMARY':'false','HERALD_STATUS_EXPORT':'false','WEEKLY_SYNTHESIS':'true',
         'WEEKLY_SYNTHESIS_DAY':'sun','WEEKLY_SYNTHESIS_HOUR':'4'}
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(reg.__file__).parent,env=env,capture_output=True,text=True,check=True)
    assert "day_of_week='sun'" in result.stdout and "hour='4'" in result.stdout
    assert 'day=\'1\'' not in result.stdout


def test_write_failure_is_reported_and_next_import_repairs_pair(project,monkeypatch):
    snapshot(project)
    original=reg._atomic_write
    def write(path,text):
        if path.name.endswith('_summary.md'): raise OSError('simulated disk failure')
        original(path,text)
    monkeypatch.setattr(reg,'_atomic_write',write)
    assert reg.refresh_project('Demo')['status']=='error'
    assert not reg.summary_info('Demo')['has_summary']
    monkeypatch.setattr(reg,'_atomic_write',original)
    assert reg.refresh_project('Demo')['status']=='generated'
    assert reg.refresh_project('Demo')['status']=='fresh'


def test_wrong_project_is_unfiled_and_cannot_change_current_snapshot(project):
    snapshot(project); reg.refresh_project('Demo')
    meta={'type':'handoff','project':'demo','checkpoint_version':1,'based_on':cp.identity('Demo'),'created_at':'2026-10-08T00:00:00Z'}
    (project/'handoffs'/'wrong.md').write_text(frontmatter.dumps(frontmatter.Post(body(),**meta)))
    reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='fresh'
    assert any(g['claimed']=='demo' for g in reg.unfiled_groups())
    with pytest.raises(ValueError,match='exact project slug'):
        cp.parse(meta,body(),'Demo')


def test_checkpoint_survives_archive_and_rename_with_legacy_history(project):
    legacy(project); key=snapshot(project); reg.refresh_project('Demo')
    assert reg.set_archived('Demo',True)['status']=='ok'
    assert cp.identity('Demo')==key
    assert reg.refresh_project('Demo')['status']=='fresh'
    assert reg.set_archived('Demo',False)['status']=='ok'
    assert reg.rename('Demo','Renamed')['status']=='ok'
    assert cp.identity('Renamed')==key
    assert reg.refresh_project('Renamed')['status']=='generated'


def test_project_status_is_published_only_from_valid_checkpoint(project):
    snapshot(project,project_status='running')
    assert reg.refresh_project('Demo')['status']=='generated'
    assert reg.project('Demo')['status']=='running'
    key=cp.identity('Demo')
    meta={'type':'handoff','project':'Demo','checkpoint_version':1,'based_on':key,
          'created_at':'2026-10-08T00:00:00Z','project_status':'invented'}
    (project/'handoffs'/'invalid-status.md').write_text(frontmatter.dumps(frontmatter.Post(body(),**meta)))
    reg.invalidate()
    assert reg.refresh_project('Demo')['status']=='error'
    assert reg.project('Demo')['status']=='running'


def test_conflicts_can_be_reconciled_without_deleting_immutable_evidence(project):
    root=snapshot(project); reg.refresh_project('Demo')
    a=snapshot(project,'a.md',parent=root,content=body(state='CURRENT branch A.'))
    b=snapshot(project,'b.md',parent=root,content=body(state='CURRENT branch B.'))
    assert reg.refresh_project('Demo')['status']=='error'
    prompt=app._prompt_text('handoff','Demo')
    assert 'reconciles: [' in prompt and a in prompt and b in prompt
    assert 'branch A.' in prompt and 'branch B.' in prompt
    merged=snapshot(project,'reconciled.md',parent=root,
                    content=body(state='CURRENT reconciled both branches.'),reconciles=[a,b])
    assert reg.refresh_project('Demo')['status']=='generated'
    assert cp.identity('Demo')==merged
    assert len(list((project/'handoffs').glob('*.md')))==4
    assert 'reconciled both branches' in reg.context_info('Demo')['context']


def test_compact_export_preserves_tilde_code_fences(project):
    value=body().replace('- host /srv/demo.', '~~~text\nSTATE\nOPEN\nDONE\n~~~')
    snapshot(project,content=value)
    export=cp.export_context('Demo',compact=True).split('\n',1)[1]
    assert cp.split_context(export)['FACTS']=='~~~text\nSTATE\nOPEN\nDONE\n~~~'


def test_late_sibling_of_already_published_update_resolves_at_common_ancestor(project):
    root=snapshot(project); reg.refresh_project('Demo')
    a=snapshot(project,'a.md',parent=root,content=body(state='CURRENT branch A.'))
    reg.refresh_project('Demo')
    b=snapshot(project,'b.md',parent=root,content=body(state='CURRENT branch B.'))
    assert reg.refresh_project('Demo')['status']=='error'
    parent,ids,material=cp.resolution('Demo')
    assert parent==root and set(ids)=={a,b}
    prompt=app._prompt_text('handoff','Demo')
    assert 'based_on: '+root in prompt
    merged=snapshot(project,'merge.md',parent=parent,reconciles=ids,content=body(state='CURRENT both.'))
    assert reg.refresh_project('Demo')['checkpoint_id']==merged


def test_bootstrap_button_is_valid_javascript_and_compress_upload_still_works(project,monkeypatch):
    legacy(project)
    client=app.app.test_client()
    page=client.get('/p/Demo').get_data(as_text=True)
    assert 'const route = "consolidate";' in page
    assert 'rb-btn' not in page and 'bootstrap checkpoint with Gemini' in page
    # Run the upload operation synchronously to inspect the API contract without
    # polling threads; actual compressor generation remains unchanged.
    monkeypatch.setattr(app,'_start',lambda key,fn: app.jsonify(fn()))
    response=client.post('/api/compress',data={
        'files':(io.BytesIO(b'## Next steps\n- TODO protect this task.\n## Completed work\n- DONE fixed parser.'),'notes.md'),
        'mode':'safe','target_tokens':'3000'},content_type='multipart/form-data')
    assert response.status_code==200 and response.json['ai_calls']==0
    assert 'protect this task' in response.json['context']
    assert 'DONE fixed parser' in response.json['context']
