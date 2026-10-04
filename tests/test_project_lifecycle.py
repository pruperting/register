import frontmatter
import pytest

import register as reg


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "VAULT_PATH", tmp_path)
    reg.invalidate()
    (tmp_path / reg.PROJECTS_DIR).mkdir()
    yield tmp_path
    reg.invalidate()


def test_create_project_creates_handoffs_directory(vault):
    result = reg.create_project("Example")
    assert result["status"] == "ok"
    assert (vault / "projects" / "Example" / "handoffs").is_dir()


def test_scan_repairs_missing_handoffs_directory(vault):
    (vault / "projects" / "Existing").mkdir()
    reg.invalidate()
    assert reg.project("Existing") is not None
    assert (vault / "projects" / "Existing" / "handoffs").is_dir()


def test_archive_moves_project_into_archive(vault):
    reg.create_project("Example")
    result = reg.set_archived("Example", True)
    assert result["status"] == "ok"
    assert not (vault / "projects" / "Example").exists()
    assert (vault / "projects" / "archive" / "Example").is_dir()
    reg.invalidate()
    p = reg.project("Example")
    assert p["archived"] is True
    assert p["rel_dir"] == "projects/archive/Example"


def test_unarchive_moves_project_back(vault):
    reg.create_project("Example")
    reg.set_archived("Example", True)
    result = reg.set_archived("Example", False)
    assert result["status"] == "ok"
    assert (vault / "projects" / "Example").is_dir()
    assert not (vault / "projects" / "archive" / "Example").exists()


def test_unarchive_refuses_destination_collision(vault):
    (vault / "projects" / "Example").mkdir()
    (vault / "projects" / "archive" / "Example").mkdir(parents=True)
    result = reg.set_archived("Example", False)
    assert result["status"] == "error"
    assert "destination already exists" in result["reason"]


def test_legacy_archived_project_is_migrated(vault):
    d = vault / "projects" / "Legacy"
    d.mkdir()
    post = frontmatter.Post("")
    post.metadata["archived"] = True
    (d / "_project.md").write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    reg.invalidate()
    p = reg.project("Legacy")
    assert p["archived"] is True
    assert not d.exists()
    assert (vault / "projects" / "archive" / "Legacy").is_dir()


def test_legacy_migration_refuses_collision(vault):
    active = vault / "projects" / "Legacy"
    archived = vault / "projects" / "archive" / "Legacy"
    active.mkdir()
    archived.mkdir(parents=True)
    post = frontmatter.Post("")
    post.metadata["archived"] = True
    (active / "_project.md").write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    reg.invalidate()
    projects = reg.all_projects()
    assert active.exists()
    assert archived.exists()
    assert "Legacy" in projects


def test_archive_container_is_not_a_project(vault):
    (vault / "projects" / "archive").mkdir()
    reg.invalidate()
    assert "archive" not in reg.all_projects()


def test_archived_path_claims_nested_project_name(vault):
    d = vault / "projects" / "archive" / "Example"
    d.mkdir(parents=True)
    (d / "note.md").write_text("# note\n", encoding="utf-8")
    reg.invalidate()
    p = reg.project("Example")
    assert p["file_count"] == 1
    assert p["files"][0]["claim_source"] == "location"


def test_rename_archived_project_stays_archived(vault):
    reg.create_project("OldName")
    reg.set_archived("OldName", True)
    result = reg.rename("OldName", "NewName")
    assert result["status"] == "ok"
    assert not (vault / "projects" / "NewName").exists()
    assert (vault / "projects" / "archive" / "NewName").is_dir()
