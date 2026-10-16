"""Historical-only retired checkpoint facts, kept out of the active evidence path.

Immutable, conversation-authored retired-knowledge sidecars are the source.
<Project>_RETIRED.md is a rebuildable view and must never enter active prompts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import frontmatter

TYPE = 'retired-knowledge'
ARCHIVE_TYPE = 'retired-archive'


def _reg():
    import register
    return register


def archive_name(name: str) -> str:
    return name + '_RETIRED.md'


def archive_path(name: str):
    return _reg().project_dir(name) / archive_name(name)


def _stamp(value: object) -> str:
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('paired_created_at must be a valid ISO timestamp') from exc
    if d.tzinfo is None:
        raise ValueError('paired_created_at must include timezone')
    return d.astimezone(timezone.utc).isoformat()


def _read_retirement(rec: dict, name: str) -> dict:
    from checkpoints import split_context
    reg = _reg()
    path = reg.VAULT_PATH / rec['path']
    parsed = reg._read(path)
    if parsed is None:
        raise ValueError(f'unreadable retired knowledge: {rec["path"]}')
    meta, content = parsed
    if meta.get('type') != TYPE or meta.get('archive_version') != 1:
        raise ValueError(f'{rec["path"]}: expected type: retired-knowledge and archive_version: 1')
    if str(meta.get('project')) != name:
        raise ValueError(f'{rec["path"]}: project slug does not match {name}')
    parent = str(meta.get('retired_from') or '')
    import re
    if not re.fullmatch(r'ROOT|(?:legacy:)?[0-9a-f]{64}', parent):
        raise ValueError(f'{rec["path"]}: retired_from must be an exact prior checkpoint ID')
    stamp = _stamp(meta.get('paired_created_at'))
    if len(content) > 2_000_000:
        raise ValueError(f'{rec["path"]}: sidecar exceeds 2,000,000 characters; split source material')
    try:
        sections = split_context(content.strip())
    except ValueError as exc:
        raise ValueError(f'{rec["path"]}: {exc}') from exc
    digest = hashlib.sha256(json.dumps({'project': name, 'retired_from': parent,
        'paired_created_at': stamp, 'sections': sections}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'path': rec['path'], 'retired_from': parent, 'paired_created_at': stamp,
            'sections': sections, 'id': digest}


def _retirements(p: dict) -> list[dict]:
    return [_read_retirement(rec, p['name']) for rec in p.get('retired_sources', [])]


def require_pair(p: dict, checkpoint: dict) -> None:
    """Opt-in on new handoffs: don't publish if its retirement manifest is missing.

    Previous checkpoints without retired_sidecar: true remain backward compatible.
    """
    target = (checkpoint['parent'], _stamp(checkpoint['created_at']))
    matches = [d for d in _retirements(p)
               if (d['retired_from'], d['paired_created_at']) == target]
    identities = {d['id'] for d in matches}
    if not matches:
        raise ValueError('retired_sidecar: true but matching retired-knowledge file is missing; save both outputs before importing')
    if len(identities) != 1:
        raise ValueError('conflicting retired-knowledge sidecars for this checkpoint; reconcile them before import')


def _known_snapshots(p: dict) -> set[tuple[str, str]]:
    from checkpoints import parse
    reg = _reg()
    matched = set()
    for f in p.get('handoffs', []):
        parsed = reg._read(reg.VAULT_PATH / f['path'])
        if not parsed or 'checkpoint_version' not in parsed[0]:
            continue
        meta, body = parsed
        item = parse(meta, body, p['name'])
        matched.add((item['parent'], _stamp(item['created_at'])))
    return matched


def _render(name: str, docs: list[dict]) -> str:
    from checkpoints import SECTIONS
    blocks = ['CTX/2']
    for section in SECTIONS:
        blocks.append(section)
        wrote = False
        for d in docs:
            data = d['sections'][section].strip()
            if data == '-':
                continue
            wrote = True
            # Keep the retired claims verbatim; add provenance only outside them.
            blocks.append(f"### Retired {d['paired_created_at']} | based_on {d['retired_from']} | source {d['path']}")
            blocks.append(data)
        if not wrote:
            blocks.append('-')
    return '\n'.join(blocks) + '\n'


def sync(name: str, p: dict | None = None) -> dict:
    """Rebuild historical view from sidecars; never merges it into active state.

    Errors preserve any prior archive file and are reported separately from the
    active checkpoint's publication status.
    """
    reg = _reg()
    p = p if p is not None else reg.project(name)
    if not p:
        return {'status': 'error', 'reason': 'project not found'}
    try:
        sources = _retirements(p)
        if not sources:
            if archive_path(name).exists():
                raise ValueError('archived retirement sources missing; prior historical export retained unchanged')
            return {'status': 'empty', 'count': 0}
        known = _known_snapshots(p)
        # A sidecar can arrive before its handoff. Keep it on disk, but do not
        # claim it belongs to the historical record until a matching handoff exists.
        paired = [s for s in sources if (s['retired_from'], s['paired_created_at']) in known]
        waiting = len(sources) - len(paired)
        if not paired:
            if archive_path(name).exists():
                raise ValueError('prior retirement sources missing or unpaired; prior archive retained unchanged')
            return {'status': 'pending', 'count': 0, 'unpaired': waiting}
        dedup = {}
        pair_claims = {}
        for s in paired:
            pair = s['retired_from'], s['paired_created_at']
            previous = pair_claims.setdefault(pair, s['id'])
            if previous != s['id']:
                raise ValueError('two distinct retirement documents claim the same checkpoint; no archive updated')
            dedup.setdefault(s['id'], s)
        ordered = sorted(dedup.values(), key=lambda s: (s['paired_created_at'], s['retired_from'], s['id']))
        digest = hashlib.sha256(json.dumps([s['id'] for s in ordered], sort_keys=True).encode()).hexdigest()
        target = archive_path(name)
        ids = [s['id'] for s in ordered]
        if target.exists():
            current = reg._read(target)
            if current is None or current[0].get('type') != ARCHIVE_TYPE:
                raise ValueError('existing historical export is unreadable or not Register-generated; retained unchanged')
            previous_ids = set(current[0].get('source_ids', []))
            if previous_ids - set(ids):
                raise ValueError('previously imported retirement evidence changed or disappeared; historical export retained unchanged')
            if current[0].get('source_digest') == digest:
                return {'status': 'fresh', 'count': len(ordered), 'unpaired': waiting}
        metadata = {'type': ARCHIVE_TYPE, 'project': name, 'ctx_version': 2,
                    'source_digest': digest, 'source_count': len(ordered),
                    'source_ids': ids,
                    'generated_at': datetime.now(timezone.utc).isoformat(),
                    'warning': 'Historical, superseded material; never current project state or default AI context'}
        rendered = frontmatter.dumps(frontmatter.Post(_render(name, ordered), **metadata)) + '\n'
        reg._atomic_write(target, rendered)
        reg.invalidate()
        return {'status': 'generated', 'count': len(ordered), 'unpaired': waiting}
    except (ValueError, TypeError, OSError) as exc:
        return {'status': 'error', 'reason': str(exc)}


def export(name: str) -> str:
    """Explicit historical recovery only; never called by handoff_prompt_context."""
    reg = _reg()
    p = reg.project(name)
    if not p:
        raise ValueError('project not found')
    report = sync(name, p)
    path = archive_path(name)
    if report['status'] == 'error':
        # Do not lock the user out of a retained last-known-good recovery file
        # simply because a source was deleted or has become malformed.
        last_good = reg._read(path) if path.exists() else None
        if last_good is None or last_good[0].get('type') != ARCHIVE_TYPE:
            raise ValueError(report['reason'])
    if not path.exists():
        raise ValueError('no retired knowledge has been imported')
    return path.read_text(encoding='utf-8')
