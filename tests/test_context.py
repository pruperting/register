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


if __name__ == '__main__':
    unittest.main()
