"""Read-only, bounded literal search over files within Register project folders."""
from pathlib import Path
import re
import register

EXTENSIONS = {".md", ".markdown", ".txt"}
MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 2500
MAX_RESULTS = 100


def search(query: str):
    query = (query or "").strip()
    if not query or len(query) > 120:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    root = register.VAULT_PATH / "projects"
    if not root.is_dir():
        return []
    results = []
    examined = 0
    # Filesystem folders are used, not generated contexts; no extra database/index.
    for project in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not project.is_dir() or project.is_symlink() or project.name.startswith("_") or project.name == "archive":
            continue
        for path in sorted(project.rglob("*")):
            if examined >= MAX_FILES or len(results) >= MAX_RESULTS:
                return results
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXTENSIONS:
                continue
            if any(part.startswith(".") for part in path.relative_to(project).parts):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            examined += 1
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            for match in pattern.finditer(content):
                # Present one compact local excerpt; preserve case in the original.
                left = max(0, match.start() - 90)
                right = min(len(content), match.end() + 90)
                before = " ".join(content[left:match.start()].split())
                matched = content[match.start():match.end()]
                after = " ".join(content[match.end():right].split())
                results.append({
                    "project": project.name,
                    "file": str(path.relative_to(root.parent)),
                    "line": content.count("\n", 0, match.start()) + 1,
                    "before": ("…" if left else "") + before,
                    "match": matched,
                    "after": after + ("…" if right < len(content) else ""),
                })
                if len(results) >= MAX_RESULTS:
                    return results
    return results
