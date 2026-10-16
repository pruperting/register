"""Stage 3 deliberately uses no downloaded models or heavyweight NLP stack."""
import context_compactor as cc


def test_local_nlp_shortens_unstructured_request():
    text=("User: I was wondering if you could please provide the output. "
          "For example, show the current deployment and keep `app.py`.\n")
    out=cc.compact_nlp(text)
    assert len(out['text'])<len(text)
    assert 'e.g.' in out['text']
    assert '`app.py`' in out['text']
    assert out['fact_signatures_preserved']


def test_never_modify_negations_qualifiers_or_code():
    text=("---\ntype: handoff\n---\n"
          "# Goal\n"
          "Do not overwrite /srv/data or `CHECKPOINT_ID a39`.\n"
          "Never assume deployment 25000 is complete; it may be unverified.\n"
          "```bash\necho 'For example do not change this'\n```\n"
          "| key | for example |\n")
    out=cc.compact_nlp(text)
    assert out['text']==text


def test_does_not_change_protected_logical_signatures():
    text=("For example, do not change any paths.\n"
          "As soon as possible, verify the status; before release it is unknown.\n")
    out=cc.compact_nlp(text)
    assert out['fact_signatures_preserved']
    assert cc._literal_counts(text)==cc._literal_counts(out['text'])
    assert 'do not' in out['text']
    assert 'before release it is unknown' in out['text']


def test_no_unqualified_stopword_dropping_or_new_facts():
    src="Can you please fix the error, but only if the test has passed?\n"
    out=cc.compact_nlp(src)
    assert 'only if the test has passed?' in out['text']
    assert out['fact_signatures_preserved']
    assert cc.compact_nlp(out['text'])['text']==out['text']


def test_full_pipeline_has_three_stages_and_no_ai():
    src=("User: I was wondering if you could please test this. "
         "For example, do not write to /srv/data.\n")
    result=cc.compress_documents([('chat.txt',src)])
    assert result['status']=='generated'
    assert result['ai_calls']==0
    assert result['model']=='none'
    assert result['stage_stats'][0]['nlp_tokens']<=result['stage_stats'][0]['lexical_tokens']
    assert 'nlp_replacements' in result['stage_stats'][0]
    assert 'Please test this' in result['context']
    assert 'do not write to /srv/data' in result['context']
    assert result['verified']


def test_repeated_nlp_does_not_progressively_erode():
    source='For example, can you please show the metadata without modifying /srv/data?\n'
    one=cc.compact_nlp(source)['text']
    two=cc.compact_nlp(one)['text']
    assert one==two
