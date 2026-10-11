"""Tests for the Herald status snapshot (herald_status.py)."""
from __future__ import annotations

import herald_status as hs

CTX = """CTX/2
GOAL
- Keep Herald honest.
OPEN
- Suggested but not acted on:
- `forbid_containers` config option for `hosts.py`.
- Retention rule for `db_dumps/music_library-*.db`.
- Open:
- Whether to keep Pi-hole on N2+ (now Pi 5).
NEXT
1. Verify Garden Beacon: Confirm `/api/garden` is the Garden Beacon (ce08). Repoint `commute.garden_url` if needed.
2. Delete Stray `weather.py`: Remove `~/dockers/herald/weather.py`.
3. Reboot Optiflex: Into kernel 6.8.0-142, outside 02:00-07:00 UTC.
4. Fourth thing: not shown.
REJECTED
- Nothing.
"""


def test_subheadings_are_not_items():
    items = hs._section_items(CTX, "OPEN", limit=50)
    assert "Suggested but not acted on:" not in items
    assert "Open:" not in items
    assert len(items) == 3


def test_headline_takes_label_before_colon():
    assert hs._headline(
        "Verify Garden Beacon: Confirm `/api/garden` is ce08. Repoint it."
    ) == "Verify Garden Beacon"


def test_headline_first_sentence_and_backticks():
    h = hs._headline("`forbid_containers` config option for `hosts.py`. More text here.")
    assert h == "forbid_containers config option for hosts.py"


def test_headline_keeps_version_numbers():
    assert hs._headline("Rebooting into kernel 6.8.0-142.") == "Rebooting into kernel 6.8.0-142"


def test_headline_keeps_tags_and_short_items_whole():
    assert hs._headline("TODO T-4: inspect logs.") == "TODO T-4: inspect logs"
    assert hs._headline("Fix: the thing.") == "Fix: the thing"
    assert hs._headline("FIXME: the cache layer drops writes when the worker restarts mid-flush.") \
        == "FIXME: the cache layer drops writes when the worker restarts mid-flush"


def test_headline_skips_place_labels():
    assert hs._headline("On the Pi: tar xzf vizpi.tar.gz -C ~ and then run the installer script.") \
        .startswith("On the Pi: tar xzf")


def test_headline_is_capped():
    assert len(hs._headline("word " * 60)) <= hs.HEADLINE_CHARS


def _project(context: str, mtime: float = 1_700_000_000.0) -> dict:
    return {"name": "Herald", "status": "active", "mtime": mtime,
            "handoffs": [], "context": context}


def _run(monkeypatch, projects, previous=None):
    monkeypatch.setattr(hs.register, "invalidate", lambda: None)
    monkeypatch.setattr(hs.register, "project_list", lambda: projects)
    monkeypatch.setattr(hs, "_context_mtime", lambda n: 0.0)
    monkeypatch.setattr(hs, "_summary_mtime", lambda n: 0.0)
    monkeypatch.setattr(hs, "_latest_review", lambda now: None)
    monkeypatch.setattr(hs.checkpoints, "pending", lambda p: False)
    return hs.build_payload(previous)


def test_first_run_is_baseline_and_v1_is_rejected(monkeypatch, tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"schema_version": 1, "projects": []}')
    assert hs._load_previous(p) is None
    out = _run(monkeypatch, [_project(CTX)])
    assert out["baseline"] is True
    assert out["changes"]["new_open"] == []
    assert "_open_full" not in out["projects"][0]


def test_new_open_reported_with_project_and_summary_line(monkeypatch):
    first = _run(monkeypatch, [_project(CTX)])
    ctx2 = CTX.replace("NEXT", "- Add a battery check per sensor class: details.\nNEXT", 1)
    second = _run(monkeypatch, [_project(ctx2, mtime=1_700_000_100.0)], previous=first)

    assert second["changes"]["new_open"] == [{
        "project": "Herald",
        "id": hs._item_id("Herald", "Add a battery check per sensor class: details."),
        "item": "Add a battery check per sensor class: details.",  # verbatim
    }]
    (line,) = second["summary"]
    assert line["line"] == "Herald: 1 new open item · next: Verify Garden Beacon"
    assert line["next"] == "Verify Garden Beacon"
    # published lists stay verbatim; only the summary is shortened
    assert second["projects"][0]["next"][0].startswith("Verify Garden Beacon: Confirm")


def test_reordering_open_is_not_new(monkeypatch):
    first = _run(monkeypatch, [_project(CTX)])
    lines = CTX.splitlines()
    i = lines.index("- Retention rule for `db_dumps/music_library-*.db`.")
    lines[i], lines[i - 1] = lines[i - 1], lines[i]
    second = _run(monkeypatch, [_project("\n".join(lines))], previous=first)
    assert second["changes"]["new_open"] == []


def test_items_beyond_display_cap_still_diffed(monkeypatch):
    many = "\n".join(f"- Item {i}." for i in range(30))
    ctx = f"OPEN\n{many}\nNEXT\n1. Go.\n"
    first = _run(monkeypatch, [_project(ctx)])
    second = _run(monkeypatch, [_project(ctx.replace("- Item 29.", "- Item 29.\n- Item 30."))],
                  previous=first)
    assert [n["item"] for n in second["changes"]["new_open"]] == ["Item 30."]
    assert len(second["projects"][0]["open"]) == hs.MAX_SECTION_ITEMS
