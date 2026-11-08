"""The owner's WORKSPACE rule (backups/ first, scratch only in /tmp) must reach every AI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV_LINE = "Back up to <deploy-dir>/backups/ before changes; scratch"


def test_handoff_prompt_has_workspace_rule():
    text = (ROOT / "handoff_prompt.md").read_text()
    assert "WORKSPACE" in text
    assert "mktemp -d /tmp/<project>-work-XXXX" in text
    assert INV_LINE in text
    # the block sits with the other house rules, before the prior checkpoint
    assert text.index("WORKSPACE") < text.index("<prior_project_checkpoint>")


def test_bootstrap_prompt_carries_inv_line():
    assert INV_LINE in (ROOT / "checkpoints.py").read_text()


def test_debrief_prompt_has_house_rules():
    text = (ROOT / "debrief_prompt.md").read_text()
    assert "**House rules**" in text
    for needle in ("github.com/pruperting", ".env", "/backups/", "/tmp/<project>-work-XXXX"):
        assert needle in text
