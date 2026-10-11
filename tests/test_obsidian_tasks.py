"""Read-only Obsidian integration regressions."""
import obsidian_tasks


def test_project_notes_and_unassigned(tmp_path, monkeypatch):
    monkeypatch.setattr(obsidian_tasks.register, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(obsidian_tasks, "active_names", lambda: {"Register"})
    monkeypatch.setenv("DAILY_NOTES_DIR", "daily")
    folder = tmp_path / "daily"
    folder.mkdir()
    (folder / "2026-10-11.md").write_text("""# Today
## Existing projects
### [[Register]]
- [ ] #high Wire up tasks
- [x] Old note finished
- Important correction in the notes
### [[Regster]]
- [ ] This must not silently land in Register
## New projects / ideas
### [[InterestingIdea]]
- [ ] Research this
""")
    data = obsidian_tasks.scan()
    assert len(data["tasks"]) == 2
    assert len(data["unassigned"]) == 2
    assert len(data["updates"]) == 1
    assert data["tasks"][0]["priority"] == "high"
    assert "Regster" in [x["claimed_project"] for x in data["unassigned"]]
    assert "PENDING OBSIDIAN" in obsidian_tasks.context_overlay("Register", "CTX/2", data)
    assert obsidian_tasks.context_overlay("Other", "CTX/2", data) == "CTX/2"


def test_missing_daily_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(obsidian_tasks.register, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(obsidian_tasks, "active_names", lambda: {"Register"})
    monkeypatch.setenv("DAILY_NOTES_DIR", "missing")
    assert obsidian_tasks.scan()["tasks"] == []


def test_path_traversal_rejected(monkeypatch):
    monkeypatch.setenv("DAILY_NOTES_DIR", "../outside")
    try:
        obsidian_tasks.note_root()
    except ValueError:
        pass
    else:
        assert False, "traversal should be rejected"


def test_generated_index_is_safe_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(obsidian_tasks.register, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(obsidian_tasks.register, "project_list", lambda: [
        {"name": "Register", "archived": False},
        {"name": "Herald", "archived": False},
        {"name": "Old", "archived": True},
    ])
    # Actual atomic writer is used: no model or external service.
    first = obsidian_tasks.sync_project_notes()
    assert first == {"index": "updated", "template": "updated"}
    index = (tmp_path / obsidian_tasks.INDEX_FILE).read_text()
    assert "[[Register]]" in index and "[[Herald]]" in index
    assert "[[Old]]" not in index
    assert "tp.system.suggester" in (tmp_path / obsidian_tasks.TEMPLATE_FILE).read_text()
    assert obsidian_tasks.sync_project_notes() == {"index": "unchanged", "template": "unchanged"}
    (tmp_path / obsidian_tasks.INDEX_FILE).write_text("# My own project index")
    assert obsidian_tasks.sync_project_notes()["index"] == "blocked"
    assert (tmp_path / obsidian_tasks.INDEX_FILE).read_text() == "# My own project index"
