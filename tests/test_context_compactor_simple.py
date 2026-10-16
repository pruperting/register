"""Production regression coverage for Register's lightweight upload compressor."""
import context_compactor as cc
import token_accounting as ta


def test_no_models_or_aliases_and_preserve_critical_facts(monkeypatch):
    monkeypatch.setattr(ta, 'count_tokens', lambda s: len(s))
    source = ('User: I was wondering if you could please explain. '
              'In order to test, do not overwrite /srv/data or `DB_NAME`.\n')
    result = cc.compress_documents([('conversation.md', source)])
    assert result['status'] == 'generated' and result['ai_calls'] == 0
    assert 'do not overwrite /srv/data' in result['context']
    assert '`DB_NAME`' in result['context']
    assert 'ALIASES/1' not in result['context']
    assert result['output_tokens'] < result['input_tokens']
    assert result['verified'] and 'NOT verified' in result['verification']


def test_no_gain_keeps_original_exactly(monkeypatch):
    monkeypatch.setattr(ta, 'count_tokens', lambda s: len(s))
    source = ('---\ntype: handoff\n---\nCTX/2\nGOAL\n'
              '- Preserve `app.py`, /srv/opus, and CURRENT deployment.\n')
    result = cc.compress_documents([('handoff.md', source)])
    assert result['context'] == source
    assert result['reduction_pct'] == 0
    assert result['edits'] == 0


def test_token_inflation_rejected(monkeypatch):
    # A contrived reference tokenization where concise text costs more tokens.
    monkeypatch.setattr(ta, 'count_tokens', lambda s: len(s) + (10000 if 'e.g.' in s else 0))
    original = 'For example, do not overwrite /srv/data.\n'
    result = cc.compress_documents([('a.md', original)])
    assert result['context'] == original
    assert result['output_tokens'] == result['input_tokens']
    assert not result['stage_stats'][0]['candidate_applied']


def test_multiple_documents_remain_separated(monkeypatch):
    monkeypatch.setattr(ta, 'count_tokens', lambda s: len(s))
    res = cc.compress_documents([('a.md', 'Keep this.'), ('b.md', 'Do not delete that.')])
    assert 'SOURCE_FILE 1: a.md' in res['context']
    assert 'SOURCE_FILE 2: b.md' in res['context']
    assert res['files'] == 2


def test_tokencounter_counts_offline(monkeypatch):
    class Encoder:
        def encode(self, text, disallowed_special=()):
            assert disallowed_special == ()
            return list(range(len(text.split())))
    monkeypatch.setattr(ta, 'get_encoder', lambda: Encoder())
    assert ta.count_tokens('test the output') == 3
    assert ta.count_tokens('') == 0
