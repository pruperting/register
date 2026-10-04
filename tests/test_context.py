import os
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import register


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        register.VAULT_PATH = Path(self.t.name)
        self.project_dir = register.VAULT_PATH / 'projects' / 'Demo'
        self.handoffs = self.project_dir / 'handoffs'
        self.handoffs.mkdir(parents=True)
        (self.project_dir / '_project.md').write_text(
            '---\ndescription: demo\nstatus: building\n---\n', encoding='utf-8')
        register.invalidate()

    def tearDown(self):
        self.t.cleanup()
        register.invalidate()

    def _handoff(self, name, title, body, mtime):
        path = self.handoffs / name
        path.write_text(
            f'---\ntype: handoff\nproject: Demo\ntitle: {title}\n---\n{body}\n',
            encoding='utf-8')
        os.utime(path, (mtime, mtime))
        register.invalidate()
        return path

    def test_context_rebuild_is_deterministic_and_freshness_aware(self):
        self._handoff('handoff-1.md', 'first',
                      '## What changed\n- CURRENT app.py works.\n\n## Next steps\n- Test it.', 1000)
        r = register.generate_context('Demo')
        self.assertEqual(r['status'], 'generated')
        info = register.context_info('Demo')
        self.assertTrue(info['context_verified'])
        self.assertIn('CURRENT app.py works.', info['context'])
        self.assertEqual(register.generate_context('Demo')['status'], 'fresh')

        self._handoff('handoff-2.md', 'second',
                      '## What changed\n- CURRENT new feature is live.', 2000)
        r2 = register.generate_context('Demo')
        self.assertEqual(r2['status'], 'generated')
        self.assertIn('CURRENT new feature is live.', register.context_info('Demo')['context'])


    def test_context_refuses_implicit_reference_fallback(self):
        # Remove canonical handoffs and leave only a legacy AI conversation.
        for path in self.handoffs.iterdir():
            path.unlink()
        convo = register.VAULT_PATH / 'ai-conversations' / 'claude' / 'Demo'
        convo.mkdir(parents=True)
        (convo / 'old-chat.md').write_text(
            '---\nproject: Demo\ntitle: old chat\n---\nCURRENT secret legacy fact\n',
            encoding='utf-8')
        register.invalidate()

        result = register.generate_context('Demo')
        self.assertEqual(result['status'], 'error')
        self.assertIn('no canonical material', result['reason'])
        self.assertFalse(register.context_info('Demo')['has_context'])

    def test_explicit_bootstrap_creates_compact_canonical_handoff_then_context(self):
        convo = register.VAULT_PATH / 'ai-conversations' / 'claude' / 'Demo'
        convo.mkdir(parents=True)
        (convo / 'old-chat.md').write_text(
            '---\nproject: Demo\ntitle: old chat\n---\n@ you asked\nmessage time: yesterday\n## What changed\n- CURRENT legacy feature works.\n',
            encoding='utf-8')
        register.invalidate()

        canonical = '''# Legacy reference bootstrap
## Objective
- Continue Demo.
## Current state
- CURRENT legacy feature works.
## Environment and deployment
- not documented
## Decisions and constraints
- not documented
## Corrections to previous records
none
## Open issues
- not documented
## Next steps
- Verify current runtime.
## Technical anchors
- `app.py`
'''
        seen = {}
        old_complete = register._complete
        register._complete = lambda system, prompt, validator, expected, **kwargs: (
            seen.update(prompt=prompt, backend=kwargs.get('backend')) or
            canonical if validator(canonical) else (_ for _ in ()).throw(AssertionError('invalid fixture')))
        try:
            result = register.bootstrap_handoff('Demo')
        finally:
            register._complete = old_complete

        self.assertEqual(result['status'], 'generated')
        self.assertEqual(result['source_mode'], 'explicit-reference-bootstrap')
        self.assertEqual(result['ai_calls'], 1)
        self.assertLessEqual(result['estimated_tokens'], 4500)
        self.assertIn('DETERMINISTIC LEGACY EVIDENCE', seen['prompt'])
        register.invalidate()
        project = register.project('Demo')
        self.assertEqual(project['handoff_count'], 1)
        self.assertGreaterEqual(project['reference_count'], 1)
        self.assertEqual(project['conversation_count'], 1)
        handoff = next(self.handoffs.iterdir()).read_text(encoding='utf-8')
        self.assertIn('source_mode: explicit-reference-bootstrap', handoff)
        self.assertIn('evidence_engine: deterministic-v14', handoff)
        self.assertNotIn('@ you asked', handoff)
        self.assertNotIn('message time:', handoff)

        ctx = register.generate_context('Demo')
        self.assertEqual(ctx['status'], 'generated')
        self.assertEqual(ctx['source_mode'], 'authoritative-state-tasks-handoffs')
        info = register.context_info('Demo')
        self.assertEqual(info['context_source_mode'], 'authoritative-state-tasks-handoffs')

    def test_bootstrap_rejects_transcript_shaped_ai_output(self):
        convo = register.VAULT_PATH / 'ai-conversations' / 'claude' / 'Demo'
        convo.mkdir(parents=True)
        (convo / 'old-chat.md').write_text(
            '---\nproject: Demo\ntitle: old chat\n---\nCURRENT legacy feature works.\n',
            encoding='utf-8')
        register.invalidate()

        bad = '''# Legacy reference bootstrap
## Objective
@ you asked
## Current state
- CURRENT legacy feature works.
## Environment and deployment
-
## Decisions and constraints
-
## Corrections to previous records
none
## Open issues
-
## Next steps
-
## Technical anchors
-
'''
        old_complete = register._complete
        def fake_complete(system, prompt, validator, expected, **kwargs):
            self.assertFalse(validator(bad))
            raise RuntimeError('model produced invalid output twice')
        register._complete = fake_complete
        try:
            result = register.bootstrap_handoff('Demo')
        finally:
            register._complete = old_complete
        self.assertEqual(result['status'], 'error')
        self.assertIn('invalid output', result['reason'])
        self.assertEqual(list(self.handoffs.iterdir()), [])

    def test_bootstrap_is_refused_when_handoff_history_exists(self):
        self._handoff('existing.md', 'existing', '## What changed\n- CURRENT state.', 1000)
        result = register.bootstrap_handoff('Demo')
        self.assertEqual(result['status'], 'error')
        self.assertIn('already has handoff history', result['reason'])

    def test_explicit_correction_supersedes_matching_earlier_active_fact(self):
        docs = [
            ('old.md', '''## Environment and deployment\n- CURRENT `OLLAMA_URL=http://old:11434`'''),
            ('new.md', '''## Corrections to previous records\n- CORRECTION | PREVIOUS: `OLLAMA_URL=http://old:11434` | CURRENT: `OLLAMA_URL=http://new:11434` | AFFECTS: status, AI context, runbook | EVIDENCE: runtime configuration'''),
        ]
        out = register._deterministic_compress(docs, profile='dense', target_tokens=700)
        self.assertEqual(out['corrections'], 1)
        self.assertEqual(out['corrections_reconciled'], 1)
        self.assertIn('CORRECTION_PRECEDENCE', out['context'])
        self.assertIn('CURRENT: `OLLAMA_URL=http://new:11434`', out['context'])
        state = out['context'].split('\nSTATE\n', 1)[1].split('\nCORRECTIONS\n', 1)[0]
        self.assertNotIn('OLLAMA_URL=http://old:11434', state)

    def test_correction_chain_is_never_deduplicated(self):
        docs = [
            ('one.md', '## Corrections to previous records\n- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | AFFECTS: AI context | EVIDENCE: first verification'),
            ('two.md', '## Corrections to previous records\n- CORRECTION | PREVIOUS: port 5050 | CURRENT: port 6060 | AFFECTS: AI context | EVIDENCE: second verification'),
        ]
        out = register._deterministic_compress(docs, target_tokens=700)
        self.assertEqual(out['corrections'], 2)
        self.assertIn('CURRENT: port 5050', out['context'])
        self.assertIn('CURRENT: port 6060', out['context'])

    def test_correction_is_hard_protected_even_under_small_budget(self):
        filler = '\n'.join(f'- historical observation {i} with several ordinary words' for i in range(200))
        docs = [('old.md', '## What changed\n' + filler),
                ('new.md', '''## Corrections to previous records\n- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | AFFECTS: status, AI context, runbook | EVIDENCE: verified deployment''')]
        out = register._deterministic_compress(docs, profile='dense', target_tokens=700)
        self.assertFalse(out['missing_hard'])
        self.assertIn('CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050', out['context'])

    def test_large_project_batches_get_global_correction_override(self):
        old_size = register.LARGE_PROJECT_BATCH_DOCS
        try:
            register.LARGE_PROJECT_BATCH_DOCS = 1
            docs = [
                ('one', '## What changed\n- CURRENT port 5000'),
                ('two', '## Corrections to previous records\n- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | AFFECTS: status, AI context, runbook | EVIDENCE: verified deployment'),
            ]
            joined, batches = register._batch_project_material('Demo', docs)
        finally:
            register.LARGE_PROJECT_BATCH_DOCS = old_size
        self.assertEqual(len(batches), 2)
        self.assertIn('GLOBAL CORRECTION OVERRIDES — AUTHORITATIVE', joined)
        self.assertIn('CURRENT: port 5050', joined)

    def test_none_correction_section_is_not_a_correction(self):
        docs = [('x', '## Corrections to previous records\nnone')]
        self.assertFalse(register._documents_have_corrections(docs))


    def test_refresh_project_regenerates_runbook_for_new_correction(self):
        self._handoff('handoff-correction.md', 'correction',
                      '## Corrections to previous records\n- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | AFFECTS: status, AI context, runbook | EVIDENCE: verified deployment',
                      3000)
        calls = []
        old_ctx, old_sum, old_rb = register.generate_context, register.generate_summary, register.generate_runbook
        register.generate_context = lambda *a, **k: calls.append('context') or {'status': 'generated'}
        register.generate_summary = lambda *a, **k: calls.append('summary') or {'status': 'generated'}
        register.generate_runbook = lambda *a, **k: calls.append('runbook') or {'status': 'generated'}
        try:
            result = register.refresh_project('Demo')
        finally:
            register.generate_context, register.generate_summary, register.generate_runbook = old_ctx, old_sum, old_rb
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(calls, ['context', 'summary', 'runbook'])
        self.assertTrue(result['correction_runbook_refresh'])


    def test_summary_state_semantics_keeps_next_distinct_from_current(self):
        context = '''CTX/2
STATE
- CURRENT service is running.
DEC
- Playstyle removal is agreed.
OPEN
- Path join remains unresolved.
NEXT
- Remove playstyle from calculate_tags_optimized.py and apply_tags_optimized.py.
REJECTED
-
'''
        guard = register._summary_state_semantics(context)
        self.assertIn('CURRENT / IMPLEMENTED EVIDENCE', guard)
        self.assertIn('CURRENT service is running.', guard)
        self.assertIn('DECISIONS / CONSTRAINTS — NOT IMPLEMENTATION BY ITSELF', guard)
        self.assertIn('UNRESOLVED — MUST REMAIN UNRESOLVED', guard)
        self.assertIn('FUTURE WORK — MUST NOT BE DESCRIBED AS COMPLETED', guard)
        self.assertIn('Remove playstyle from calculate_tags_optimized.py', guard)

    def test_summary_prompt_forbids_upgrading_planned_work_to_completed(self):
        self._handoff('handoff-summary-state.md', 'state semantics',
                      '''## What changed
- CURRENT service is running.

## Decisions and constraints
- Playstyle removal is agreed.

## Open issues
- Path join remains unresolved.

## Next steps
- Remove playstyle from calculate_tags_optimized.py and apply_tags_optimized.py.''',
                      4000)
        seen = {}
        safe = '''## Overview
Demo project.

## Where it stands
The service is running. Playstyle removal has been agreed but is still pending. The path join remains unresolved.

## Pick up here
Remove playstyle from the two scripts, then resolve the path join.'''
        old_complete = register._complete
        def fake_complete(system, prompt, validator, expected, **kwargs):
            seen['prompt'] = prompt
            self.assertTrue(validator(safe))
            return safe
        register._complete = fake_complete
        try:
            result = register.generate_summary('Demo', full=True)
        finally:
            register._complete = old_complete
        self.assertEqual(result['status'], 'generated')
        prompt = seen['prompt']
        self.assertIn('NEXT is future work', prompt)
        self.assertIn('A decision to do something is not evidence that it has been implemented', prompt)
        self.assertIn('FUTURE WORK — MUST NOT BE DESCRIBED AS COMPLETED', prompt)
        self.assertIn('Remove playstyle from calculate_tags_optimized.py', prompt)

    def test_state_overrides_historical_context_section(self):
        self._handoff('old.md', 'old', '## What changed\n- CURRENT service uses port 5000.', 1000)
        register.all_projects()
        state_text = '# Project State\n\n## Current\nService uses port 5050.\n\n## Architecture\n\n## Environment\n\n## Constraints\n\n## Decisions in force\n'
        register.set_state('Demo', state_text)
        result = register.generate_context('Demo', full=True)
        self.assertEqual(result['status'], 'generated')
        ctx = register.context_info('Demo')['context']
        state = ctx.split('\nSTATE\n', 1)[1].split('\nCORRECTIONS\n', 1)[0]
        self.assertIn('Service uses port 5050.', state)
        self.assertNotIn('port 5000', state)
        self.assertTrue(result['source_state'])

    def test_tasks_override_stale_handoff_next_state(self):
        self._handoff('old.md', 'old', '## Next steps\n- Remove playstyle support.', 1000)
        register.all_projects()
        task = register.add_task('Demo', 'Remove playstyle support')['task']
        register.update_task('Demo', task['id'], status='done')
        result = register.generate_context('Demo', full=True)
        self.assertEqual(result['status'], 'generated')
        ctx = register.context_info('Demo')['context']
        next_body = ctx.split('\nNEXT\n', 1)[1].split('\nREJECTED\n', 1)[0]
        state = ctx.split('\nSTATE\n', 1)[1].split('\nCORRECTIONS\n', 1)[0]
        self.assertNotIn('Remove playstyle support', next_body)
        self.assertIn('DONE: Remove playstyle support', state)
        self.assertEqual(result['source_tasks'], 1)

    def test_task_change_invalidates_fresh_context_without_new_handoff(self):
        self._handoff('one.md', 'one', '## What changed\n- CURRENT app works.', 1000)
        register.all_projects()
        self.assertEqual(register.generate_context('Demo', full=True)['status'], 'generated')
        self.assertEqual(register.generate_context('Demo')['status'], 'fresh')
        register.add_task('Demo', 'Ship release')
        second = register.generate_context('Demo')
        self.assertEqual(second['status'], 'generated')
        self.assertIn('TODO: Ship release', register.context_info('Demo')['context'])

    def test_state_change_invalidates_fresh_context_without_new_handoff(self):
        self._handoff('one.md', 'one', '## What changed\n- CURRENT app works.', 1000)
        register.all_projects()
        self.assertEqual(register.generate_context('Demo', full=True)['status'], 'generated')
        self.assertEqual(register.generate_context('Demo')['status'], 'fresh')
        register.set_state('Demo', '# Project State\n\n## Current\nNew current truth.\n\n## Architecture\n\n## Environment\n\n## Constraints\n\n## Decisions in force')
        rebuilt = register.generate_context('Demo')
        self.assertEqual(rebuilt['status'], 'generated')
        self.assertIn('New current truth.', register.context_info('Demo')['context'])

    def test_state_or_tasks_can_generate_context_without_handoffs(self):
        register.all_projects()
        register.set_state('Demo', '# Project State\n\n## Current\nState-only project is live.\n\n## Architecture\n\n## Environment\n\n## Constraints\n\n## Decisions in force')
        result = register.generate_context('Demo')
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(result['source_handoffs'], 0)
        self.assertTrue(result['source_state'])
        self.assertIn('State-only project is live.', register.context_info('Demo')['context'])

if __name__ == '__main__':
    unittest.main()
