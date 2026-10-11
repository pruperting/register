"""Search is literal, read-only, project-scoped, and bounded."""
import project_search


def test_literal_phrase_and_context(tmp_path, monkeypatch):
    monkeypatch.setattr(project_search.register, "VAULT_PATH", tmp_path)
    folder = tmp_path / "projects" / "Register"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("first line\nA Gemini Review was saved.\nLast line")
    result = project_search.search("gemini review")
    assert len(result) == 1
    assert result[0]["project"] == "Register"
    assert result[0]["file"] == "projects/Register/notes.md"
    assert result[0]["line"] == 2
    assert result[0]["match"] == "Gemini Review"
    assert "saved" in result[0]["after"]
    assert project_search.search("Gemini.*Review") == []


def test_excludes_internal_archives_binary_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(project_search.register, "VAULT_PATH", tmp_path)
    root = tmp_path / "projects"
    for name in ("Register", "_estate", "archive"):
        (root / name).mkdir(parents=True)
        (root / name / "test.md").write_text("uniqueXYZ")
    (root / "Register" / "binary.jpg").write_text("uniqueXYZ")
    (root / "Register" / "linked.md").symlink_to(root / "_estate" / "test.md")
    result = project_search.search("uniqueXYZ")
    assert len(result) == 1 and result[0]["file"] == "projects/Register/test.md"
    assert project_search.search("") == []
    assert project_search.search("x" * 121) == []
