import tempfile
from pathlib import Path
import unittest

import register


class ProjectStateTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        register.VAULT_PATH = Path(self.t.name)
        self.project_dir = register.VAULT_PATH / "projects" / "Demo"
        self.project_dir.mkdir(parents=True)
        (self.project_dir / "_project.md").write_text("---\nstatus: building\n---\n", encoding="utf-8")
        register.invalidate()

    def tearDown(self):
        self.t.cleanup()
        register.invalidate()

    def test_scan_self_heals_state_without_counting_it_as_reference(self):
        p = register.project("Demo")
        state = self.project_dir / "STATE.md"
        self.assertTrue(state.exists())
        self.assertFalse(p["state_populated"])
        self.assertEqual(p["reference_count"], 0)
        self.assertNotIn("STATE.md", [f["path"] for f in p["files"]])

    def test_create_project_creates_state(self):
        result = register.create_project("Fresh")
        self.assertEqual(result["status"], "ok")
        path = register.VAULT_PATH / "projects" / "Fresh" / "STATE.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("type: project-state", text)
        self.assertIn("project: Fresh", text)

    def test_set_state_records_authoritative_content(self):
        register.project("Demo")
        content = "# Project State\n\n## Current\n\nAPI is live.\n\n## Architecture\n\nFlask + markdown vault."
        result = register.set_state("Demo", content)
        self.assertEqual(result["status"], "ok")
        info = register.state_info("Demo")
        self.assertTrue(info["state_populated"])
        self.assertIn("API is live.", info["state"])
        raw = (self.project_dir / "STATE.md").read_text(encoding="utf-8")
        self.assertIn("updated_at:", raw)
        self.assertIn("project: Demo", raw)

    def test_archive_round_trip_preserves_state(self):
        register.project("Demo")
        register.set_state("Demo", "# Project State\n\n## Current\n\nStill true.")
        self.assertEqual(register.set_archived("Demo", True)["status"], "ok")
        archived = register.VAULT_PATH / "projects" / "archive" / "Demo" / "STATE.md"
        self.assertTrue(archived.exists())
        self.assertIn("Still true.", archived.read_text(encoding="utf-8"))
        self.assertEqual(register.set_archived("Demo", False)["status"], "ok")
        self.assertTrue(register.state_info("Demo")["state_populated"])

    def test_rename_preserves_state_and_rewrites_identity(self):
        register.project("Demo")
        register.set_state("Demo", "# Project State\n\n## Current\n\nRename me.")
        result = register.rename("Demo", "Renamed")
        self.assertEqual(result["status"], "ok")
        path = register.VAULT_PATH / "projects" / "Renamed" / "STATE.md"
        raw = path.read_text(encoding="utf-8")
        self.assertIn("project: Renamed", raw)
        self.assertIn("Rename me.", raw)

    def test_merge_carries_only_populated_state(self):
        other = register.VAULT_PATH / "projects" / "Other"
        other.mkdir(parents=True)
        (other / "_project.md").write_text("---\nstatus: building\n---\n", encoding="utf-8")
        register.invalidate()
        register.project("Demo")
        register.project("Other")
        register.set_state("Other", "# Project State\n\n## Current\n\nSource truth.")
        result = register.merge(["Other"], "Demo")
        self.assertEqual(result["status"], "ok")
        self.assertIn("Source truth.", register.state_info("Demo")["state"])

    def test_merge_refuses_two_populated_states(self):
        other = register.VAULT_PATH / "projects" / "Other"
        other.mkdir(parents=True)
        (other / "_project.md").write_text("---\nstatus: building\n---\n", encoding="utf-8")
        register.invalidate()
        register.project("Demo")
        register.project("Other")
        register.set_state("Demo", "# Project State\n\n## Current\n\nTarget truth.")
        register.set_state("Other", "# Project State\n\n## Current\n\nSource truth.")
        result = register.merge(["Other"], "Demo")
        self.assertEqual(result["status"], "error")
        self.assertIn("reconcile state explicitly", result["reason"])
        self.assertTrue((other / "STATE.md").exists())
        self.assertTrue((self.project_dir / "STATE.md").exists())


if __name__ == "__main__":
    unittest.main()
