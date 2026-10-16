"""Register's lightweight local-only lexical text compactor.

NOT semantic summarisation. Changed passages are auditable;
critically important literal/negation tokens are checked. Inputs are not stored.
No external libraries, network requests, or learned model required.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass

# The replacements are intentionally conservative. No unqualified stopword,
# pronoun, negation or temporal-qualifier removal. Ordered longest first.
PHRASES = (
    ("in spite of the fact that", "although"),
    ("due to the fact that", "because"),
    ("in the event that", "if"),
    ("for the purpose of", "for"),
    ("with the exception of", "except"),
    ("at this point in time", "now"),
    ("in order to", "to"),
    ("make use of", "use"),
    ("makes use of", "uses"),
    ("making use of", "using"),
    ("prior to", "before"),
    ("subsequent to", "after"),
    ("on a daily basis", "daily"),
    ("on a weekly basis", "weekly"),
    ("as a result of", "because of"),
    ("in relation to", "about"),
    ("has the ability to", "can"),
    ("have the ability to", "can"),
    ("is able to", "can"),
    ("are able to", "can"),
    ("it is important to note that", ""),
    ("it is worth noting that", ""),
)
PATTERNS = [(re.compile(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", re.I), b, a) for a, b in PHRASES]
INLINE_CODE = re.compile(r"(`+)(?!`)(.*?)\1|https?://[^\s)>]+|\$\$.*?\$\$|\$[^$\n]+\$", re.S)
# A conservative lexical fact signature: numbers, negation, explicit logical
# qualifiers, backtick literals, env names, paths, links, issue references.
FACTS = re.compile(
    r"`[^`\n]+`|https?://[^\s)>]+|(?<!\w)/(?:[\w.~-]+/)*[\w.~-]+"
    r"|\b(?:not|never|no|only|unless|except|must|should|cannot|can't|without|"
    r"before|after|until|at least|at most|may|might|possibly|unknown|unverified|"
    r"false|true)\b|(?-i:\b[A-Z][A-Z0-9_]{2,}\b)|\b\d+(?:[.:/-]\d+)*\b",
    re.I,
)
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(?:[^\n]*)$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LIST = re.compile(r"^\s{0,3}(?:[-*+]\s|\d+[.)]\s)")
RAW_TEXT = re.compile(r"^(?:\s{4,}|\s*\|.*\||\s*>|\s*<[/!A-Za-z]|\s*\{[\[\{]|\s*[\}\]])")
COMMAND = re.compile(r"^\s*(?:docker|git|curl|python\d*|pip|sudo|ssh|scp|rsync|tar|rm|cp|mv|export|cd|GET|POST|PUT|DELETE)\s")


def estimate_tokens(s: str) -> int:
    """Exactly Register's provider-neutral token estimate, not model tokens."""
    return max(1, round(len(s) / 4)) if s else 0


def _literal_counts(text: str) -> Counter:
    return Counter(m.group().casefold() for m in FACTS.finditer(text))


def _replace_prose(text: str) -> tuple[str, int]:
    """Transform only prose, keeping URLs, math and inline code byte-identical."""
    total = 0
    pieces = []
    prev = 0
    for match in INLINE_CODE.finditer(text):
        segment, count = _replace_phrases(text[prev:match.start()])
        pieces.extend((segment, match.group()))
        total += count
        prev = match.end()
    segment, count = _replace_phrases(text[prev:])
    pieces.append(segment)
    total += count
    candidate = ''.join(pieces)
    # Never accept a rewrite that loses even one protected lexical signature.
    if _literal_counts(candidate) != _literal_counts(text):
        return text, 0
    return candidate, total


def _replace_phrases(s: str) -> tuple[str, int]:
    total = 0
    for pattern, repl, _ in PATTERNS:
        # An intentional conservative context: substitutions are not applied
        # inside quoted literal values or code fragments (handled outside).
        def match_replace(m):
            nonlocal total
            total += 1
            if m.group()[:1].isupper() and repl:
                return repl[:1].upper() + repl[1:]
            return repl
        s = pattern.sub(match_replace, s)
    return s, total


def compact(text: str, *, stages: int = 2) -> dict:
    """Stage 1 = whitespace/Markdown cleanup; stage 2 = safe phrase compaction.

    Does not infer current truth, merge distant facts, or remove entire content
    sections. A full audit records every changed line. No input mutation.
    """
    if stages not in (1, 2):
        raise ValueError('stages must be 1 or 2')
    t0 = time.monotonic()
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized.splitlines(keepends=True)
    out = []
    fence_char = None
    frontmatter = bool(lines and lines[0].strip() == '---')
    frontmatter_done = False
    blank_count = 0
    edits = []
    replacements = 0
    protected = 0
    removed_blanks = 0

    for index, line in enumerate(lines, start=1):
        body = line[:-1] if line.endswith('\n') else line
        ending = '\n' if line.endswith('\n') else ''
        stripped = body.strip()
        fence = FENCE.match(body)
        in_fm = frontmatter and not frontmatter_done
        if in_fm and index > 1 and stripped == '---':
            frontmatter_done = True
        in_fence = fence_char is not None
        if fence:
            if fence_char is None:
                fence_char = fence.group(1)[0]
            elif fence_char == fence.group(1)[0]:
                fence_char = None
        strict = bool(in_fm or in_fence or fence or RAW_TEXT.match(body) or
                      body.lstrip().startswith(('<!--', '-->', 'CTX/2', 'CHECKPOINT_ID ')) or
                      COMMAND.match(body) or (stripped.isupper() and len(stripped) <= 24))
        if strict:
            protected += 1
            out.append(line)
            blank_count = 0
            continue
        if not stripped:
            # Retain one separator; do not touch frontmatter, code, tables.
            blank_count += 1
            if blank_count > 1:
                removed_blanks += 1
                edits.append({'line': index, 'kind': 'extra-blank', 'before': line, 'after': ''})
                continue
            out.append(ending or '\n')
            continue
        blank_count = 0
        # Whitespace stripping is limited to trailing whitespace. Deliberate
        # indentation before text is untouched.
        stage1 = body if re.search(r' {2,}$', body) else body.rstrip(' \t')
        candidate = stage1
        count = 0
        if stages == 2 and not HEADING.match(candidate):
            # Avoid changing headings, which can be structural anchors.
            if LIST.match(candidate):
                prefix = LIST.match(candidate).group(0)
                rewritten, count = _replace_prose(candidate[len(prefix):])
                candidate = prefix + rewritten
            else:
                candidate, count = _replace_prose(candidate)
        # Strict rollback of anything that changes protected technical markers.
        if _literal_counts(candidate) != _literal_counts(body):
            candidate, count = body, 0
        if candidate != body:
            edits.append({'line': index, 'kind': 'phrase' if count else 'spacing',
                          'before': body, 'after': candidate})
        replacements += count
        out.append(candidate + ending)
    result = ''.join(out)
    # Avoid negative 'compression' from unexpectedly introduced characters.
    if len(result) > len(text):
        result = text
        edits = []
        replacements = 0
    before = estimate_tokens(text)
    after = estimate_tokens(result)
    return {'text': result, 'input_tokens': before, 'output_tokens': after,
            'reduction_pct': round(100 * (1 - after / before), 2) if before else 0.0,
            'edits': edits, 'phrase_replacements': replacements,
            'removed_blank_lines': removed_blanks, 'protected_lines': protected,
            'elapsed_s': round(time.monotonic() - t0, 3),
            'stages': stages, 'fact_signatures_preserved': _literal_counts(text) == _literal_counts(result)}



# Stage 3: a deliberately small, reviewed subset of lexical NLP techniques.
# Inspired by the independent 'less-tokens' project's filler/abbreviation
# approach, without pulling in its large OCR/embedding/model dependencies.
# Absolutely no general stop-word deletion or stemming: these lose facts.
# Each replacement is auditable, and cannot remove critical lexical signatures.
_STAGE3_PAIRS = (
    ('I was wondering if you could please', 'Please'),
    ('I was wondering if you could', 'Please'),
    ('I would appreciate it if you could', 'Please'),
    ('Could you please', 'Please'),
    ('Can you please', 'Please'),
    ('Would you be able to', 'Please'),
    ('Please kindly', 'Please'),
    ('For example', 'e.g.'),
    ('For instance', 'e.g.'),
    ('In other words', 'i.e.'),
    ('As soon as possible', 'ASAP'),
    ('With respect to', 'regarding'),
    ('With regard to', 'regarding'),
    ('At the present time', 'currently'),
    ('At the moment', 'currently'),
    ('Approximately', 'approx.'),
    ('Make sure that', 'ensure'),
    ('It should be noted that', ''),
)
_STAGE3_PROTECTED = re.compile(
    r"(`+)(?!`)(.*?)\1|https?://[^\s)>]+|\$\$.*?\$\$|\$[^$\n]+\$"
    r"|\[[^]\n]+\]\([^)\n]+\)|\"[^\"\n]*\"", re.S)
_STAGE3_RULES = [(re.compile(r'(?<![\w])'+re.escape(a)+r'(?![\w])',re.I), b)
                 for a,b in sorted(_STAGE3_PAIRS, key=lambda r:-len(r[0]))]


def _nlp_rewrite(segment: str) -> tuple[str, int]:
    """Local lexical edits, not a semantic summariser."""
    total=0
    for pattern, replacement in _STAGE3_RULES:
        def change(m):
            nonlocal total
            total+=1
            text=replacement
            # Keep the first letter's case when replacement starts in prose.
            if m.group()[:1].islower() and text:
                text=text[:1].lower()+text[1:]
            return text
        segment=pattern.sub(change,segment)
    # No double spaces caused by deleting a phrase.
    segment=re.sub(r'(?<=\S) {2,}(?=\S)', ' ', segment)
    return segment,total


def compact_nlp(text: str) -> dict:
    """Stage 3, per-line guarded filler/abbreviation pass. No headings needed.

    The audit records every changed line; no file content is stored. This stage
    never changes code, tables, frontmatter, headings, inline literals, or
    command-like lines; all guarded literal counts must remain identical.
    """
    t0=time.monotonic()
    lines=text.splitlines(keepends=True)
    frontmatter=bool(lines and lines[0].strip()=='---')
    in_frontmatter=frontmatter
    fence_char=None
    out=[]; edits=[]; replacements=0; rejected=0
    for n,line in enumerate(lines,1):
        body=line[:-1] if line.endswith('\n') else line
        ending='\n' if line.endswith('\n') else ''
        raw=body.strip()
        fence=FENCE.match(body)
        strict=bool(in_frontmatter or fence_char is not None or fence
                    or RAW_TEXT.match(body) or HEADING.match(body)
                    or COMMAND.match(body)
                    or body.lstrip().startswith(('<!--','-->','CTX/2','CHECKPOINT_ID '))
                    or (raw.isupper() and len(raw)<=24))
        if fence:
            if fence_char is None: fence_char=fence.group(1)[0]
            elif fence_char==fence.group(1)[0]: fence_char=None
        if in_frontmatter and n>1 and raw=='---': in_frontmatter=False
        if strict:
            out.append(line)
            continue
        parts=[];last=0;count=0
        # Reuse stage 2's inline-code, math and URL protection.
        for m in _STAGE3_PROTECTED.finditer(body):
            piece,k=_nlp_rewrite(body[last:m.start()]);parts.extend((piece,m.group()))
            count+=k;last=m.end()
        piece,k=_nlp_rewrite(body[last:]);parts.append(piece);count+=k
        result=''.join(parts)
        if _literal_counts(result)!=_literal_counts(body) or len(result)>len(body):
            rejected+=int(result!=body)
            result=body;count=0
        if result!=body:
            edits.append({'line':n,'kind':'nlp-lexical','before':body,'after':result})
        replacements+=count
        out.append(result+ending)
    result=''.join(out)
    if _literal_counts(result)!=_literal_counts(text) or len(result)>len(text):
        result=text;edits=[];replacements=0
    return {'text':result,'input_tokens':estimate_tokens(text),
            'output_tokens':estimate_tokens(result),
            'reduction_pct':round(100*(1-estimate_tokens(result)/estimate_tokens(text)),2) if text else 0.0,
            'edits':edits,'nlp_replacements':replacements,
            'rejected_rewrites':rejected,'elapsed_s':round(time.monotonic()-t0,3),
            'fact_signatures_preserved':_literal_counts(text)==_literal_counts(result)}

def compress_documents(documents: list[tuple[str, str]], progress=None) -> dict:
    """On-demand, CPU-local lexical compaction; never a semantic summary.

    For each document apply Markdown cleanup, conservative phrase replacement,
    and guarded NLP phrases. Keep the ORIGINAL document when this cannot save
    real cl100k_base reference tokens. Do not edit the canonical vault.
    """
    from token_accounting import count_tokens, ENCODING_NAME

    docs = [(str(name), text) for name, text in documents if text.strip()]
    if not docs:
        return {'status': 'error', 'reason': 'no readable content'}

    outputs = []
    stats = []
    audit = []
    for name, source in docs:
        if progress:
            progress(f'Markdown cleanup: {name}')
        first = compact(source, stages=1)
        if progress:
            progress(f'Conservative phrase shortening: {name}')
        second = compact(first['text'], stages=2)
        if progress:
            progress(f'Guarded lexical shortening: {name}')
        third = compact_nlp(second['text'])

        source_tokens = count_tokens(source)
        candidate_tokens = count_tokens(third['text'])
        signatures_ok = _literal_counts(source) == _literal_counts(third['text'])
        # Accept no semantic risk or token inflation merely for cosmetic edits.
        applied = signatures_ok and candidate_tokens < source_tokens
        output = third['text'] if applied else source
        edits = (
            [dict(file=name, stage='markdown', **e) for e in first['edits']]
            + [dict(file=name, stage='phrase', **e) for e in second['edits']]
            + [dict(file=name, stage='lexical', **e) for e in third['edits']]
        ) if applied else []
        audit.extend(edits)
        stats.append({
            'file': name,
            'initial_tokens': source_tokens,
            'markdown_tokens': count_tokens(first['text']),
            'lexical_tokens': count_tokens(second['text']),
            'nlp_tokens': candidate_tokens,
            'final_tokens': count_tokens(output),
            'edits': len(edits),
            'phrase_replacements': second['phrase_replacements'] if applied else 0,
            'nlp_replacements': third['nlp_replacements'] if applied else 0,
            'nlp_rejected_rewrites': third['rejected_rewrites'],
            'candidate_applied': applied,
            'fact_signatures_preserved': _literal_counts(source) == _literal_counts(output),
        })
        outputs.append(output)

    if len(outputs) == 1:
        result = outputs[0]
    else:
        result = '\n\n'.join(
            f'SOURCE_FILE {i}: {name}\n{body}\nEND_SOURCE_FILE {i}'
            for i, ((name, _), body) in enumerate(zip(docs, outputs), 1)
        )
    input_tokens = sum(count_tokens(text) for _, text in docs)
    output_tokens = count_tokens(result)
    signature_checks = all(s['fact_signatures_preserved'] for s in stats)
    return {
        'status': 'generated', 'context': result, 'engine': 'local-lexical',
        'model': 'none', 'ai_calls': 0,
        'verified': signature_checks,
        'verification': 'Technical signatures checked; semantic completeness NOT verified',
        'tokenizer': ENCODING_NAME,
        'tokenizer_scope': 'cl100k_base reference tokens, not Gemini exact tokens',
        'input_tokens': input_tokens, 'output_tokens': output_tokens,
        'estimated_input_tokens': sum(estimate_tokens(t) for _,t in docs),
        'estimated_output_tokens': estimate_tokens(result),
        'reduction_pct': round(100 * (1 - output_tokens / input_tokens), 2) if input_tokens else 0,
        'ratio': round(input_tokens / output_tokens, 3) if output_tokens else 0,
        'files': len(docs), 'stage_stats': stats,
        'edits': len(audit), 'audit': audit[:120],
        'audit_truncated': len(audit) > 120,
        'warning': (
            'Local lexical compaction only: no AI calls or semantic summarisation. '
            'Technical signatures are checked, but factual completeness is not '
            'proven. Dense AI-authored handoffs usually show 0% improvement. '
            'For canonical project updates use the full-replacement handoff '
            'prompt, not this compressor.'),
    }
