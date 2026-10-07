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
        self.assertIn('no handoff material', result['reason'])
        self.assertFalse(register.context_info('Demo')['has_context'])



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



    def test_latest_context_baseline_replaces_older_handoff_history(self):
        self._handoff('old.md', 'old',
                      '## What changed\n- CURRENT stale historical state.\n'
                      '## Next steps\n- Old task that should be absorbed by baseline.', 1000)
        baseline = self._handoff('baseline.md', 'baseline',
                                 '## Current state\n- CURRENT consolidated state.\n'
                                 '## Next steps\n- Only real remaining task.', 2000)
        text = baseline.read_text(encoding='utf-8')
        text = text.replace('title: baseline\n',
                            'title: baseline\ncontext_baseline: true\n')
        baseline.write_text(text, encoding='utf-8')
        os.utime(baseline, (2000, 2000))
        self._handoff('later.md', 'later',
                      '## What changed\n- CURRENT later feature added.', 3000)
        register.invalidate()

        docs, _ = register._all_material(register.project('Demo'))
        joined = '\n'.join(body for _, body in docs)
        self.assertNotIn('stale historical state', joined)
        self.assertNotIn('Old task that should be absorbed', joined)
        self.assertIn('CURRENT consolidated state.', joined)
        self.assertIn('CURRENT later feature added.', joined)
        self.assertEqual(len(docs), 2)

    def test_manifest_baseline_keeps_unabsorbed_handoff_even_with_older_mtime(self):
        old = self._handoff(
            'old.md', 'old',
            '## Current state\n- CURRENT stale historical state.', 1000)
        baseline = self._handoff(
            'baseline.md', 'baseline',
            '## Current state\n- CURRENT consolidated state.', 3000)
        later = self._handoff(
            'later.md', 'later',
            '## Current state\n- CURRENT later state.', 2000)

        old_rel = str(old.relative_to(register.VAULT_PATH))
        text = baseline.read_text(encoding='utf-8')
        text = text.replace(
            'title: baseline\n',
            'title: baseline\n'
            'context_baseline: true\n'
            f'source_handoff_paths: ["{old_rel}"]\n')
        baseline.write_text(text, encoding='utf-8')
        os.utime(baseline, (3000, 3000))
        os.utime(later, (2000, 2000))
        register.invalidate()

        docs, _ = register._all_material(register.project('Demo'))
        joined = '\n'.join(body for _, body in docs)

        self.assertEqual(len(docs), 2)
        self.assertIn('CURRENT consolidated state.', joined)
        self.assertIn('CURRENT later state.', joined)
        self.assertNotIn('CURRENT stale historical state.', joined)


    def test_created_at_orders_post_baseline_handoffs_independent_of_mtime(self):
        old = self._handoff(
            'old.md', 'old',
            '## Current state\n- CURRENT historical.', 1000)
        baseline = self._handoff(
            'baseline.md', 'baseline',
            '## Current state\n- CURRENT baseline.', 5000)
        first = self._handoff(
            'first.md', 'first',
            '## Current state\n- CURRENT first post-baseline.', 4000)
        second = self._handoff(
            'second.md', 'second',
            '## Current state\n- CURRENT second post-baseline.', 2000)

        old_rel = str(old.relative_to(register.VAULT_PATH))
        btext = baseline.read_text(encoding='utf-8').replace(
            'title: baseline\n',
            'title: baseline\n'
            'context_baseline: true\n'
            f'source_handoff_paths: ["{old_rel}"]\n')
        baseline.write_text(btext, encoding='utf-8')

        for path, title, stamp in (
            (first, 'first', '2026-10-07T10:00:00.000001Z'),
            (second, 'second', '2026-10-07T11:00:00.000001Z'),
        ):
            text = path.read_text(encoding='utf-8')
            text = text.replace(
                f'title: {title}\n',
                f'title: {title}\ncreated_at: {stamp}\n')
            path.write_text(text, encoding='utf-8')

        os.utime(first, (4000, 4000))
        os.utime(second, (2000, 2000))
        register.invalidate()

        docs, _ = register._all_material(register.project('Demo'))
        self.assertEqual([title for title, _ in docs],
                         ['baseline', 'first', 'second'])

    def test_context_freshness_uses_source_digest_not_mtime(self):
        first = self._handoff(
            'first.md', 'first',
            '## Current state\n- CURRENT first state.', 5000)
        text = first.read_text(encoding='utf-8').replace(
            'title: first\n',
            'title: first\ncreated_at: 2026-10-07T10:00:00.000001Z\n')
        first.write_text(text, encoding='utf-8')
        os.utime(first, (5000, 5000))
        register.invalidate()

        initial = register.generate_context('Demo')
        self.assertEqual(initial['status'], 'generated')
        self.assertEqual(register.generate_context('Demo')['status'], 'fresh')

        second = self._handoff(
            'second.md', 'second',
            '## Current state\n- CURRENT second state.', 1000)
        text = second.read_text(encoding='utf-8').replace(
            'title: second\n',
            'title: second\ncreated_at: 2026-10-07T11:00:00.000001Z\n')
        second.write_text(text, encoding='utf-8')
        os.utime(second, (1000, 1000))
        register.invalidate()

        rebuilt = register.generate_context('Demo')
        self.assertEqual(rebuilt['status'], 'generated')
        self.assertIn('CURRENT second state.',
                      register.context_info('Demo')['context'])

    def test_handoff_prompt_declares_precise_created_at(self):
        prompt_source = (Path(register.__file__).with_name(
            'handoff_prompt.md')).read_text(encoding='utf-8')
        app_source = (Path(register.__file__).with_name(
            'app.py')).read_text(encoding='utf-8')
        self.assertIn('created_at: <CREATED_AT>', prompt_source)
        self.assertIn(
            'template = template.replace("<CREATED_AT>", created_at)',
            app_source)

    def test_newer_handoff_replaces_state_open_next_snapshots(self):
        docs = [
            ('baseline.md',
             '## Current state\n'
             '- CURRENT stale state overlay is active.\n'
             '- Latest verified suite: 45 passed.\n'
             '## Open issues\n'
             '- Historical issue already resolved.\n'
             '## Next steps\n'
             '- Deploy obsolete v14 zip.'),
            ('session.md',
             '## Current state\n'
             '- CURRENT handoffs are canonical evolving evidence.\n'
             '- Latest verified suite: 38 passed.\n'
             '## Open issues\n'
             '- Verify the new baseline flow.\n'
             '## Next steps\n'
             '- Trial another project after Register verification.\n'
             '## Corrections to previous records\n'
             '- CORRECTION | PREVIOUS: older handoffs referenced test counts such as 45 passed | CURRENT: latest verified suite is 38 passed | AFFECTS: AI context | EVIDENCE: current test run'),
        ]

        out = register._deterministic_compress(
            docs, profile='dense', target_tokens=3000)
        context = out['context']

        self.assertNotIn('stale state overlay is active', context)
        self.assertNotIn('Latest verified suite: 45 passed.', context)
        self.assertNotIn('Historical issue already resolved', context)
        self.assertNotIn('Deploy obsolete v14 zip', context)
        self.assertIn('handoffs are canonical evolving evidence', context)
        self.assertIn('Latest verified suite: 38 passed.', context)
        self.assertIn('Verify the new baseline flow', context)
        self.assertIn('Trial another project after Register verification', context)
        self.assertIn('CORRECTION | PREVIOUS:', context)

    def test_snapshot_section_falls_back_when_newer_handoff_omits_it(self):
        docs = [
            ('baseline.md',
             '## Current state\n'
             '- CURRENT old state.\n'
             '## Open issues\n'
             '- Still-open baseline issue.\n'
             '## Next steps\n'
             '- Still-valid baseline next step.'),
            ('session.md',
             '## Current state\n'
             '- CURRENT new state.'),
        ]

        out = register._deterministic_compress(
            docs, profile='dense', target_tokens=2000)
        context = out['context']

        self.assertNotIn('CURRENT old state.', context)
        self.assertIn('CURRENT new state.', context)
        self.assertIn('Still-open baseline issue.', context)
        self.assertIn('Still-valid baseline next step.', context)

    def test_dedupe_prefers_newest_repeated_next_item(self):
        docs = [
            ('one.md', '## Next steps\n- Deploy the refreshed Register container.'),
            ('two.md', '## Next steps\n- Deploy the refreshed Register container.'),
        ]
        units = register._parse_units(docs, reconcile=False)
        deduped = register._dedupe_units(units)
        matches = [u for u in deduped
                   if 'Deploy the refreshed Register container.' in u['text']]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['order'], max(u['order'] for u in units))

    def test_identical_corrections_dedupe_but_chain_survives(self):
        docs = [
            ('one.md', '## Corrections to previous records\n'
             '- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | '
             'AFFECTS: AI context | EVIDENCE: verified'),
            ('two.md', '## Corrections to previous records\n'
             '- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5050 | '
             'AFFECTS: AI context | EVIDENCE: verified'),
            ('three.md', '## Corrections to previous records\n'
             '- CORRECTION | PREVIOUS: port 5050 | CURRENT: port 6060 | '
             'AFFECTS: AI context | EVIDENCE: verified later'),
        ]
        units = register._parse_units(docs, reconcile=False)
        deduped = register._dedupe_units(units)
        corrections = [u for u in deduped if u['section'] == 'CORRECTIONS']
        self.assertEqual(len(corrections), 2)
        joined = '\n'.join(u['text'] for u in corrections)
        self.assertIn('CURRENT: port 5050', joined)
        self.assertIn('CURRENT: port 6060', joined)






    def test_consolidation_budget_scales_with_evidence(self):
        small = register._consolidation_budget(4000, 2)
        medium = register._consolidation_budget(20000, 15)
        large = register._consolidation_budget(100000, 48)

        self.assertEqual(small, {
            "target_tokens": 3000,
            "ceiling_tokens": 5000,
            "generation_tokens": 6000,
        })
        self.assertEqual(medium, {
            "target_tokens": 7500,
            "ceiling_tokens": 11250,
            "generation_tokens": 12937,
        })
        self.assertEqual(large, {
            "target_tokens": 12000,
            "ceiling_tokens": 15000,
            "generation_tokens": 17250,
        })

    def test_consolidation_budget_never_exceeds_15000_ceiling(self):
        for evidence_tokens, docs in (
            (1, 1), (10000, 10), (50000, 50), (500000, 500)
        ):
            budget = register._consolidation_budget(evidence_tokens, docs)
            self.assertLessEqual(budget["ceiling_tokens"], 15000)
            self.assertLessEqual(budget["target_tokens"], 12000)
            self.assertLessEqual(budget["generation_tokens"], 18000)
            self.assertGreaterEqual(
                budget["ceiling_tokens"], budget["target_tokens"])


if __name__ == '__main__':
    unittest.main()
