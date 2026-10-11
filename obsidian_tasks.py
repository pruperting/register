"""Read-only Obsidian daily-note inbox, independent of checkpoint authority."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, timedelta
from pathlib import Path

import register

HEADING = re.compile(r"^#{2,4}\s+(.+?)\s*$")
PROJECT_LINK = re.compile(r"^\[\[([^]|#]+)(?:\|[^]]+)?\]\]$")
TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRIORITY = re.compile(r"(?:#urgent|#high|🔺|⏫|\[priority:\s*(?:high|urgent)\])", re.I)
FENCE = re.compile(r"^\s*(?:```|~~~)")
MAX_FILES = 400
MAX_BYTES = 128_000


def active_names():
    return {p["name"] for p in register.project_list() if not p["archived"]}


def note_root():
    setting = os.environ.get("DAILY_NOTES_DIR", "daily")
    path = Path(setting)
    if path.is_absolute() or ".." in path.parts or not setting.strip():
        raise ValueError("DAILY_NOTES_DIR must be a relative vault directory")
    return register.VAULT_PATH / path


def _notes():
    root = note_root()
    if not root.is_dir():
        return []
    # Limited traversal: date-named Markdown files only; no generated project
    # docs or migraine entries can be accidentally treated as a daily note.
    candidates = []
    for p in root.rglob("*.md"):
        if p.is_symlink() or not p.is_file() or not DATE_NAME.fullmatch(p.stem):
            continue
        try:
            if p.stat().st_size <= MAX_BYTES:
                candidates.append(p)
        except OSError:
            continue
    return sorted(candidates, reverse=True)[:MAX_FILES]


def scan():
    """Return actionable note tasks and project updates; never mutate notes."""
    names = active_names()
    tasks, updates, unmatched = [], [], []
    for path in _notes():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            rel = path.relative_to(register.VAULT_PATH).as_posix()
        except (OSError, UnicodeError, ValueError):
            continue
        section = None
        project = None
        fence = False
        in_frontmatter = bool(lines and lines[0].strip() == "---")
        for n, line in enumerate(lines, 1):
            if in_frontmatter:
                if n > 1 and line.strip() == "---":
                    in_frontmatter = False
                continue
            if FENCE.match(line):
                fence = not fence
                continue
            if fence:
                continue
            heading = HEADING.match(line)
            if heading:
                title = heading.group(1).strip()
                if line.startswith("## "):
                    section = title.casefold()
                    project = None
                else:
                    link = PROJECT_LINK.fullmatch(title)
                    project = link.group(1).strip() if link else None
                    if section not in ("existing projects", "project updates", "new projects / ideas"):
                        project = None
                continue
            if not project:
                continue
            match = TASK.match(line)
            if match:
                checked, content = match.groups()
                item = {"id": hashlib.sha256((rel + ":" + str(n) + ":" + content).encode()).hexdigest()[:20],
                        "project": project if project in names else None,
                        "claimed_project": project, "text": content,
                        "done": checked.lower() == "x",
                        "priority": "high" if PRIORITY.search(content) else "normal",
                        "path": rel, "line": n, "date": path.stem, "source": "obsidian"}
                if item["project"]:
                    tasks.append(item)
                else:
                    unmatched.append(item)
            elif project in names and section in ("existing projects", "project updates"):
                bullet = BULLET.match(line)
                if bullet and not line.lstrip().startswith(("- [", "* [")):
                    updates.append({"project": project, "text": bullet.group(1),
                                    "path": rel, "line": n, "date": path.stem})
    tasks.sort(key=lambda t: (t["done"], t["priority"] != "high", -int(t["date"].replace("-", "")), t["path"], t["line"]))
    return {"tasks": tasks, "updates": updates, "unassigned": unmatched}


def project_inbox(name, data=None):
    data = data or scan()
    tasks = [t for t in data["tasks"] if t["project"] == name]
    updates = [u for u in data["updates"] if u["project"] == name]
    if not tasks and not updates:
        return ""
    result = ["PENDING OBSIDIAN DAILY-NOTE EVIDENCE (not an accepted checkpoint)",
              "Review and reconcile these dated items. Do not silently mark checkpoint tasks DONE.",
              "An unchecked task is OPEN; a checked task is evidence of completion only for that exact note task."]
    for t in tasks:
        result.append(f"- [{'x' if t['done'] else ' '}] {t['text']} (source: {t['path']}:{t['line']}; priority: {t['priority']})")
    for u in updates:
        result.append(f"- NOTE: {u['text']} (source: {u['path']}:{u['line']})")
    return "\n".join(result) + "\n"


def context_overlay(name, checkpoint, data=None):
    pending = project_inbox(name, data)
    if not pending:
        return checkpoint
    if checkpoint.startswith("CHECKPOINT_ID "):
        first, separator, rest = checkpoint.partition("\n")
        return first + separator + pending + "\n--- ACCEPTED IMMUTABLE CHECKPOINT BELOW ---\n" + rest
    return pending + "\n--- ACCEPTED IMMUTABLE CHECKPOINT BELOW ---\n" + checkpoint


def project_index():
    """Deterministic markdown for an Obsidian project picker/index."""
    projects = sorted((p for p in register.project_list() if not p["archived"]),
                      key=lambda p: p["name"].casefold())
    return "# Register project index\n\nGenerated from Register. Copy an exact link into the Existing projects section of your daily note.\n\n" + "".join(f"- [[{p['name']}]]\n" for p in projects)


def checkpoint_tasks(name):
    """Extract OPEN/NEXT from an accepted snapshot, without changing state."""
    import checkpoints
    import herald_status
    result = register.refresh_project(name)
    if result.get("status") not in ("generated", "fresh"):
        return []
    info = register.context_info(name)
    if info.get("context_source_mode") != "conversation-checkpoint":
        return []
    context = info.get("context") or ""
    items = []
    for section in ("NEXT", "OPEN"):
        for i, value in enumerate(herald_status._section_items(context, section, limit=100)):
            if value.strip() == "-":
                continue
            items.append({"project": name, "text": value, "source": "checkpoint",
                          "priority": "normal", "done": False, "section": section,
                          "id": hashlib.sha256(f"{name}:{section}:{i}:{value}".encode()).hexdigest()[:20]})
    return items


def dashboard():
    data = scan()
    all_tasks = [t for t in data["tasks"] if not t["done"]]
    for p in sorted(active_names()):
        all_tasks.extend(checkpoint_tasks(p))
    all_tasks.sort(key=lambda t: (t["source"] != "obsidian", t["priority"] != "high",
                                  t.get("section") != "NEXT", t["project"], t["text"]))
    return {"tasks": all_tasks, "unassigned": data["unassigned"],
            "done": [t for t in data["tasks"] if t["done"]], "updates": data["updates"]}

# Only Register's Project Index is managed automatically.
MANAGED_MARKER = "<!-- register-managed:obsidian-projects-v1 -->"
INDEX_FILE = "Register Project Index.md"


def sync_project_notes():
    """Write only Register's own index; never replace an unmanaged user note."""
    destination = register.VAULT_PATH / INDEX_FILE
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        return {"index": "blocked"}
    body = MANAGED_MARKER + "\n" + project_index()
    if destination.exists():
        try:
            previous = destination.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {"index": "blocked"}
        if not previous.startswith(MANAGED_MARKER):
            return {"index": "blocked"}
        if previous == body:
            return {"index": "unchanged"}
    register._atomic_write(destination, body)
    return {"index": "updated"}
