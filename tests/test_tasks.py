import tempfile
from pathlib import Path
import unittest

import register


class TaskLifecycleTests(unittest.TestCase):
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

    def test_scan_self_heals_tasks_file_without_counting_it_as_reference(self):
        p = register.project("Demo")
        self.assertTrue((self.project_dir / "tasks.md").exists())
        self.assertEqual(p["task_count"], 0)
        self.assertEqual(p["reference_count"], 0)
        self.assertNotIn("tasks.md", [f["path"] for f in p["files"]])

    def test_create_project_creates_tasks_ledger(self):
        result = register.create_project("Fresh")
        self.assertEqual(result["status"], "ok")
        path = register.VAULT_PATH / "projects" / "Fresh" / "tasks.md"
        self.assertTrue(path.exists())
        self.assertIn("type: project-tasks", path.read_text(encoding="utf-8"))

    def test_archive_round_trip_preserves_task_ledger(self):
        register.add_task("Demo", "Survive archive", "doing")
        archived = register.set_archived("Demo", True)
        self.assertEqual(archived["status"], "ok")
        archived_tasks = register.VAULT_PATH / "projects" / "archive" / "Demo" / "tasks.md"
        self.assertTrue(archived_tasks.exists())
        self.assertIn("[T001] Survive archive", archived_tasks.read_text(encoding="utf-8"))
        restored = register.set_archived("Demo", False)
        self.assertEqual(restored["status"], "ok")
        self.assertEqual(register.tasks_info("Demo")["task_counts"]["doing"], 1)

    def test_task_lifecycle_uses_stable_ids_and_markdown_states(self):
        first = register.add_task("Demo", "Inspect schema")
        second = register.add_task("Demo", "Fix importer", "blocked")
        self.assertEqual(first["task"]["id"], "T001")
        self.assertEqual(second["task"]["id"], "T002")
        moved = register.update_task("Demo", "T001", status="doing")
        self.assertEqual(moved["task"]["status"], "doing")
        edited = register.update_task("Demo", "T001", text="Inspect database schema")
        self.assertEqual(edited["task"]["id"], "T001")
        register.update_task("Demo", "T001", status="done")
        info = register.tasks_info("Demo")
        self.assertEqual(info["task_counts"], {"todo": 0, "doing": 0, "blocked": 1, "done": 1})
        text = (self.project_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- [x] [T001] Inspect database schema", text)
        self.assertIn("- [ ] [T002] Fix importer", text)

    def test_checking_task_in_obsidian_marks_it_done(self):
        register.add_task("Demo", "Tick me")
        path = self.project_dir / "tasks.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [ ] [T001] Tick me", "- [x] [T001] Tick me"), encoding="utf-8")
        register.invalidate()
        self.assertEqual(register.tasks_info("Demo")["task_counts"]["done"], 1)

    def test_delete_and_validation(self):
        register.add_task("Demo", "Keep me")
        register.add_task("Demo", "Delete me")
        self.assertEqual(register.delete_task("Demo", "T002")["status"], "ok")
        self.assertEqual(register.delete_task("Demo", "T999")["status"], "error")
        self.assertEqual(register.add_task("Demo", "   ")["status"], "error")
        self.assertEqual(register.add_task("Demo", "x", "unknown")["status"], "error")

    def test_rename_preserves_tasks_and_rewrites_project_identity(self):
        register.add_task("Demo", "Carry forward", "doing")
        result = register.rename("Demo", "Renamed")
        self.assertEqual(result["status"], "ok")
        path = register.VAULT_PATH / "projects" / "Renamed" / "tasks.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("project: Renamed", text)
        self.assertIn("[T001] Carry forward", text)
        self.assertEqual(register.tasks_info("Renamed")["task_counts"]["doing"], 1)

    def test_merge_combines_tasks_without_id_collisions(self):
        other = register.VAULT_PATH / "projects" / "Other"
        other.mkdir(parents=True)
        (other / "_project.md").write_text("---\nstatus: building\n---\n", encoding="utf-8")
        register.invalidate()
        register.project("Other")
        register.add_task("Demo", "Target task")
        register.add_task("Other", "Source task", "blocked")
        result = register.merge(["Other"], "Demo")
        self.assertEqual(result["status"], "ok")
        info = register.tasks_info("Demo")
        self.assertEqual([t["id"] for t in info["tasks"]], ["T001", "T002"])
        self.assertEqual(info["task_counts"]["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
