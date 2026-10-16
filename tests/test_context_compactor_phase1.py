"""No-network tests for Register's local-only compactor."""
import io
import os
from pathlib import Path
import context_compactor as cc


def test_arbitrary_conversation_without_headings():
    source = ('User: In order to test this, please make use of the existing container.\n'
              'Assistant: Due to the fact that this is read-only, no files may be overwritten.\n'
              'User: Do not assume the latest deployment passed.\n')
    stage1=cc.compact(source,stages=1)
    stage2=cc.compact(stage1['text'], stages=2)
    assert stage2['output_tokens'] < stage1['output_tokens']
    assert 'To test this' in stage2['text']
    assert 'Do not assume' in stage2['text']
    assert 'no files may be overwritten' in stage2['text']
    assert stage2['fact_signatures_preserved']


def test_markdown_code_frontmatter_tables_and_inline_values_unchanged():
    source = ('---\ntype: handoff\nbased_on: 4e1516d2\n---\n'
              '# Summary\n\n\nIn order to avoid mistakes, do not change `CHECKPOINT_ID 88` or /vault/projects/Chimera.\n'
              '\n| Field | Value |\n|---|---|\n| key | should not change |\n'
              '```bash\n# In order to test\necho "must never change 25000"\n```\n')
    result=cc.compact(source, stages=2)
    assert source.split('```bash')[1] == result['text'].split('```bash')[1]
    assert '| key | should not change |' in result['text']
    assert 'based_on: 4e1516d2' in result['text']
    assert '`CHECKPOINT_ID 88`' in result['text']
    assert '/vault/projects/Chimera' in result['text']
    assert cc._literal_counts(source) == cc._literal_counts(result['text'])


def test_markdown_two_space_hardbreak_remains():
    source='A line with a Markdown break  \nNext line.\n'
    assert cc.compact(source,stages=2)['text']==source


def test_no_dropped_notes_due_to_headings_or_profiles():
    source = 'ARCH\n- Must never write to the upstream DB.\nFILES\n- Code at `app.py`.\nREJECTED\n- Do not use the old algorithm.\n'
    assert cc.compact(source,stages=2)['text'] == source
    assert cc.compress_documents([('ctx.md',source)])['ai_calls']==0


def test_multiple_sources_have_boundaries_and_no_ai_calls():
    docs=[('a.md','In order to help, use Git.'),('b.md','Do not overwrite /srv/data.')]
    r=cc.compress_documents(docs)
    assert r['status']=='generated' and r['ai_calls']==0
    assert 'SOURCE_FILE 1: a.md' in r['context']
    assert 'SOURCE_FILE 2: b.md' in r['context']
    assert r['verified']


def test_no_semantic_completeness_claim():
    r=cc.compress_documents([('a.md','In order to test, do not remove data.')])
    assert 'NOT verified' in r['verification']
    assert 'audit' in r and 'stage_stats' in r


def test_actual_attached_chimera_and_register_context_if_available():
    root=Path('/mnt/data')
    for name in ('Register_CONTEXT(3).md', 'chimera2-ratings-clashes-handoff-2026-10-15.md'):
        path=root/name
        if not path.exists():
            continue
        source=path.read_text(encoding='utf-8')
        result=cc.compress_documents([(name,source)])
        assert result['verified']
        assert result['output_tokens']<=result['input_tokens']
        for section in ('GOAL','STACK','ARCH','FILES','REJECTED','FACTS'):
            assert '\n'+section+'\n' in result['context']


def test_flask_route_integration_when_available(monkeypatch):
    # In Register, ensure /api/compress delegates to the new local compactor.
    try:
        import app
    except ImportError:
        return
    monkeypatch.setattr(app,'_start',lambda key,fn: app.jsonify(fn()))
    app.app.config['TESTING']=True
    resp=app.app.test_client().post('/api/compress',data={
        'files': (io.BytesIO(b'In order to do this, do not modify the DB.'),'notes.md')
    },content_type='multipart/form-data')
    assert resp.status_code==200
    data=resp.get_json()
    assert data['engine']=='local-lexical'
    assert data['ai_calls']==0
    assert 'To do this' in data['context']
