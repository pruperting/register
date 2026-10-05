import os
import sys
import tempfile
from pathlib import Path
import unittest

os.environ["AUTO_SUMMARY"] = "false"
os.environ["MONTHLY_SYNTHESIS"] = "false"
os.environ["HERALD_STATUS_EXPORT"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import register
import app


class HandoffPromptTests(unittest.TestCase):

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        register.VAULT_PATH = Path(self.t.name)

        self.project_dir = register.VAULT_PATH / "projects" / "Demo"
        self.handoffs = self.project_dir / "handoffs"
        self.handoffs.mkdir(parents=True)

        (self.project_dir / "_project.md").write_text(
            """---
description: demo project
status: building
repo: https://example.invalid/demo
---
""",
            encoding="utf-8",
        )

        register.invalidate()

    def tearDown(self):
        register.invalidate()
        self.t.cleanup()

    def _write_context(self):
        (self.project_dir / "Demo_CONTEXT.md").write_text(
            """---
type: project-context
project: Demo
generated_at: 2026-10-05T20:00:00Z
generated_by: deterministic-v14
source_mode: handoffs
context_through: 1000
estimated_tokens: 500
verified: deterministic-protected
---

CTX/2
MODE deterministic
PROFILE balanced
GOAL
- Keep Demo useful.
STACK
- Runs with Docker Compose.
ARCH
- Flask application.
FILES
- lots of file detail that the handoff prompt does not need
STATE
- CURRENT service is running.
CORRECTIONS
- CORRECTION | PREVIOUS: port 5000 | CURRENT: port 5557 | AFFECTS: AI context | EVIDENCE: verified runtime
DEC
- Keep handoffs canonical.
INV
- Do not infer completion from a proposal.
BUG
- Docker recreation can matter.
OPEN
- Authentication remains unresolved.
NEXT
- Add project-specific handoff prompts.
REJECTED
- REJECTED manual task management.
FACTS
- historical low-value fact
""",
            encoding="utf-8",
        )
        register.invalidate()

    def test_handoff_prompt_context_selects_state_bearing_sections(self):
        self._write_context()

        checkpoint = register.handoff_prompt_context("Demo")

        self.assertIn("GOAL", checkpoint)
        self.assertIn("CURRENT service is running.", checkpoint)
        self.assertIn("CORRECTION | PREVIOUS: port 5000", checkpoint)
        self.assertIn("Authentication remains unresolved.", checkpoint)
        self.assertIn("Add project-specific handoff prompts.", checkpoint)
        self.assertIn("REJECTED manual task management.", checkpoint)

        self.assertNotIn("lots of file detail", checkpoint)
        self.assertNotIn("historical low-value fact", checkpoint)

    def test_project_specific_prompt_is_scoped_and_contains_checkpoint(self):
        self._write_context()

        prompt = app._prompt_text("handoff", "Demo")

        self.assertIn("project: Demo", prompt)
        self.assertIn("PROJECT: Demo", prompt)
        self.assertIn("https://example.invalid/demo", prompt)
        self.assertIn("CURRENT service is running.", prompt)
        self.assertIn("Authentication remains unresolved.", prompt)
        self.assertIn("Add project-specific handoff prompts.", prompt)
        self.assertIn("Use the ENTIRE conversation as the evidence", prompt)
        self.assertIn("never infer completion from silence", prompt.lower())

    def test_generic_prompt_still_contains_slug_list(self):
        prompt = app._prompt_text("handoff")

        self.assertIn("project: <SLUG>", prompt)
        self.assertIn("Demo", prompt)
        self.assertIn("Choose the project value", prompt)

    def test_new_handoff_headings_map_to_state_and_open(self):
        docs = [
            (
                "handoff.md",
                """## Current state
- CURRENT worker is deployed.

## Open issues
- Cache invalidation remains unresolved.
"""
            )
        ]

        units = register._parse_units(docs)

        current = [
            u for u in units
            if "CURRENT worker is deployed." in u.get("text", "")
        ]
        open_items = [
            u for u in units
            if "Cache invalidation remains unresolved." in u.get("text", "")
        ]

        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["section"], "STATE")

        self.assertEqual(len(open_items), 1)
        self.assertEqual(open_items[0]["section"], "OPEN")


if __name__ == "__main__":
    unittest.main()
