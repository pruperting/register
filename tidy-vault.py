#!/usr/bin/env python3
"""tidy-vault.py — inventory and clean up the Obsidian vault's projects.

Read-only by default. Every destructive action needs an explicit flag,
and --fix-junk moves files to a timestamped quarantine folder rather
than deleting them, so nothing is unrecoverable.

  ./tidy-vault.py                      # report only
  ./tidy-vault.py --fix-junk           # quarantine junk, fix .md.md names
  ./tidy-vault.py --plan-merges        # print register API merge commands
  ./tidy-vault.py --apply-merges       # execute them via the register API

Point it at the vault with --vault, and at the register with --register.
"""
import argparse
import difflib
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_VAULT = os.environ.get("VAULT_PATH", "/vault")
DEFAULT_REGISTER = os.environ.get("REGISTER_URL", "http://localhost:5557")

GENERATED = re.compile(r"(_summary\.md|_RUNBOOK\.md)$")
FM_PROJECT = re.compile(r"^---\s*\n(.*?)\n---", re.S)
FM_FIELD = re.compile(r"^project:\s*(.+?)\s*$", re.M)


def frontmatter_project(path: Path) -> str | None:
    """Read a file's `project:` frontmatter field, if any.

    The register attributes a file by frontmatter FIRST and folder name
    second. This script used to look only at folder names, so a file whose
    frontmatter had been re-pointed still showed under its old folder —
    producing merge suggestions for projects the register doesn't have,
    which then failed with "no valid source projects".
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(2048)
    except OSError:
        return None
    block = FM_PROJECT.match(head)
    if not block:
        return None
    field = FM_FIELD.search(block.group(1))
    return field.group(1).strip().strip("\"'") if field else None


def is_junk(name: str) -> str | None:
    """Return a reason string if this file is junk, else None."""
    if "sync-conflict" in name:
        return "syncthing conflict copy"
    if name.endswith(".md.md"):
        return "double extension"
    if name == "CLAUDE.md":
        return "Claude Code instructions (belongs in the repo, not the vault)"
    return None


def scan(vault: Path) -> dict:
    projects_dir = vault / "projects"
    convo_dir = vault / "ai-conversations"

    convo_projects: dict[str, int] = {}
    if convo_dir.exists():
        for provider in convo_dir.iterdir():
            if not provider.is_dir() or provider.name.startswith("."):
                continue
            for proj in provider.iterdir():
                if not proj.is_dir() or proj.name.startswith("."):
                    continue
                for f in proj.rglob("*.md"):
                    if is_junk(f.name):
                        continue
                    # Frontmatter wins over folder name, exactly as the
                    # register decides it.
                    owner = frontmatter_project(f) or proj.name
                    convo_projects[owner] = convo_projects.get(owner, 0) + 1

    project_folders: dict[str, dict] = {}
    if projects_dir.exists():
        for d in projects_dir.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            files = list(d.rglob("*.md"))
            other = [f.name for f in files
                     if not GENERATED.search(f.name)
                     and f.name != "_project.md"
                     and not is_junk(f.name)]
            project_folders[d.name] = {
                "has_meta": (d / "_project.md").exists(),
                "generated": [f.name for f in files if GENERATED.search(f.name)],
                "other": other,
            }
            # Handoff notes live under projects/<name>/ and are real
            # material — a project fed only by handoffs is active, not
            # orphaned.
            if other:
                convo_projects[d.name] = convo_projects.get(d.name, 0) + len(other)

    for f in vault.rglob("*.md"):
        rel = f.relative_to(vault)
        if any(p.startswith(".") for p in rel.parts):
            continue
        if rel.parts[0] in (projects_dir.name, convo_dir.name):
            continue          # already counted above
        if is_junk(f.name):
            continue
        owner = frontmatter_project(f)
        if owner:
            convo_projects[owner] = convo_projects.get(owner, 0) + 1

    junk = []
    for f in vault.rglob("*.md"):
        if any(p.startswith(".") for p in f.relative_to(vault).parts):
            continue
        reason = is_junk(f.name)
        if reason:
            junk.append((f, reason))

    odd_names = []
    for d in list(project_folders) + list(convo_projects):
        if re.search(r"[`'\"]|^\s|\s$", d):
            odd_names.append(d)

    # Folders differing only by case break Syncthing against Windows,
    # which cannot hold both. These need merging, not renaming.
    case_clashes: dict[str, list[str]] = {}
    for d in set(list(project_folders) + list(convo_projects)):
        case_clashes.setdefault(d.casefold(), []).append(d)
    case_clashes = {k: sorted(v) for k, v in case_clashes.items() if len(v) > 1}

    return {
        "convo": convo_projects,
        "folders": project_folders,
        "junk": junk,
        "odd_names": sorted(set(odd_names)),
        "case_clashes": case_clashes,
    }


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def title_case(name: str) -> str:
    """Same convention the register enforces: TitleCase, separators
    dropped. '_'-prefixed names are reserved and pass through."""
    name = (name or "").strip()
    if name.startswith("_"):
        return name
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) if parts else ""


def set_file_project(path: Path, target: str) -> bool:
    """Rewrite a file's `project:` frontmatter, adding a block if absent.
    Deliberately text-level so the script needs no dependencies."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    block = FM_PROJECT.match(text)
    if block:
        body = block.group(1)
        if FM_FIELD.search(body):
            new_body = FM_FIELD.sub(f"project: {target}", body, count=1)
        else:
            new_body = body.rstrip() + f"\nproject: {target}"
        new = text[:block.start(1)] + new_body + text[block.end(1):]
    else:
        new = f"---\nproject: {target}\n---\n\n" + text
    try:
        path.write_text(new, encoding="utf-8")
        return True
    except OSError:
        return False


def find_duplicates(names: list[str]) -> list[list[str]]:
    """Group names that are probably the same project."""
    groups: list[list[str]] = []
    used: set[str] = set()
    for i, a in enumerate(names):
        if a in used:
            continue
        group = [a]
        na = normalise(a)
        for b in names[i + 1:]:
            if b in used:
                continue
            nb = normalise(b)
            same = (na == nb
                    or na.startswith(nb) or nb.startswith(na)
                    or difflib.SequenceMatcher(None, na, nb).ratio() > 0.82)
            if same:
                group.append(b)
                used.add(b)
        if len(group) > 1:
            used.add(a)
            groups.append(group)
    return groups


def folder_rules(vault: Path) -> dict:
    """Apply the register's rules: a project exists only if it has a
    folder; a file belongs only if its claim matches a folder EXACTLY."""
    projects_dir = vault / "projects"
    folders = sorted(d.name for d in projects_dir.iterdir()
                     if d.is_dir() and not d.name.startswith(".")) \
        if projects_dir.exists() else []

    bad_case = [f for f in folders if f != title_case(f)]
    claims: dict[str, list[Path]] = {}
    for f in vault.rglob("*.md"):
        rel = f.relative_to(vault)
        if any(p.startswith(".") for p in rel.parts) or is_junk(f.name):
            continue
        if GENERATED.search(f.name) or f.name == "_project.md":
            continue
        claimed = frontmatter_project(f)
        if not claimed:
            if rel.parts[0] == "projects" and len(rel.parts) >= 2:
                claimed = rel.parts[1]
            elif rel.parts[0] == "ai-conversations" and len(rel.parts) >= 3:
                claimed = rel.parts[2]
        if claimed and claimed not in folders:
            claims.setdefault(claimed, []).append(f)

    # For each unmatched claim, find the folder it probably meant.
    resolved, orphan = {}, {}
    for claimed, files in claims.items():
        match = next((f for f in folders
                      if f.casefold() == claimed.casefold()
                      or title_case(f) == title_case(claimed)), None)
        (resolved if match else orphan)[claimed] = (match, files)
    return {"folders": folders, "bad_case": bad_case,
            "resolved": resolved, "orphan": orphan}


def report_rules(r: dict):
    print("\n=== FOLDER-IS-TRUTH CHECK ===\n")
    print(f"{len(r['folders'])} project folders\n")

    if r["bad_case"]:
        print("--- folders not in TitleCase ---")
        for f in r["bad_case"]:
            print(f"    {f}  →  {title_case(f)}")
        print("    fix with --apply-titlecase\n")

    if r["resolved"]:
        print("--- files claiming a near-match (fixable automatically) ---")
        for claimed, (match, files) in sorted(r["resolved"].items()):
            print(f"    {claimed!r} → {match!r}  ({len(files)} file(s))")
        print("    fix with --apply-claims\n")

    if r["orphan"]:
        print("--- files claiming a project that does not exist ---")
        print("    (these appear in the register's 'to be filed' card;")
        print("     assign or create them there)")
        for claimed, (_, files) in sorted(r["orphan"].items()):
            print(f"    {claimed!r}  ({len(files)} file(s))"
                  f"  suggested: {title_case(claimed)}")
        print()


def apply_titlecase(vault: Path, r: dict):
    base = vault / "projects"
    for f in r["bad_case"]:
        target = title_case(f)
        src, dst = base / f, base / target
        if dst.exists():
            print(f"    SKIP {f} → {target}: target exists, merge manually")
            continue
        try:
            src.rename(dst)
            print(f"    renamed {f} → {target}")
            # generated docs are named after the project; rename them too
            for old_name, new_name in (
                    (f"{f}_summary.md", f"{target}_summary.md"),
                    (f"{f}_RUNBOOK.md", f"{target}_RUNBOOK.md")):
                p = dst / old_name
                if p.exists() and not (dst / new_name).exists():
                    p.rename(dst / new_name)
        except OSError as e:
            print(f"    FAILED {f}: {e}")


def apply_claims(vault: Path, r: dict):
    fixed = 0
    for claimed, (match, files) in sorted(r["resolved"].items()):
        for f in files:
            if set_file_project(f, match):
                fixed += 1
        print(f"    {claimed!r} → {match!r}: {len(files)} file(s)")
    print(f"    {fixed} file(s) updated")


def report(data: dict, vault: Path):
    convo, folders = data["convo"], data["folders"]
    all_names = sorted(set(convo) | set(folders))

    print(f"\n=== VAULT INVENTORY: {vault} ===\n")
    print(f"{len(all_names)} distinct project names "
          f"({len(convo)} with conversations, {len(folders)} with folders)\n")

    print("--- projects with material ---")
    for name in sorted(convo, key=lambda n: -convo[n]):
        meta = "meta" if folders.get(name, {}).get("has_meta") else "    "
        gen = len(folders.get(name, {}).get("generated", []))
        print(f"  {convo[name]:4d} files  {meta}  {'sum' if gen else '   '}  {name}")

    orphans = [n for n in folders if n not in convo]
    if orphans:
        print("\n--- project folders with NO material ---")
        print("    (probably topic summaries from an older tool; candidates")
        print("     for archiving or deletion)")
        for name in sorted(orphans):
            info = folders[name]
            bits = []
            if info["generated"]:
                bits.append(f"{len(info['generated'])} generated")
            if info["other"]:
                bits.append(f"{len(info['other'])} other")
            print(f"        {name}  ({', '.join(bits) or 'empty'})")

    dupes = find_duplicates(all_names)
    if dupes:
        print("\n--- probable duplicate projects ---")
        for g in dupes:
            counts = {n: convo.get(n, 0) for n in g}
            target = max(counts, key=lambda n: counts[n])
            others = [n for n in g if n != target]
            print(f"    {' + '.join(f'{n}({counts[n]})' for n in g)}")
            print(f"        → suggest merging {others} into '{target}'")

    if data.get("case_clashes"):
        print("\n--- CASE COLLISIONS (breaks Syncthing on Windows) ---")
        print("    Windows cannot hold two folders differing only by case.")
        print("    Merge these, don't rename them.")
        for variants in data["case_clashes"].values():
            counts = {n: convo.get(n, 0) for n in variants}
            target = max(counts, key=lambda n: counts[n])
            print(f"    {' vs '.join(repr(v) for v in variants)}")
            print(f"        → merge {[v for v in variants if v != target]} "
                  f"into {target!r}")

    if data["odd_names"]:
        print("\n--- project names needing a rename ---")
        for n in data["odd_names"]:
            print(f"    {n!r}  (stray quote/backtick/whitespace)")

    if data["junk"]:
        print(f"\n--- junk files ({len(data['junk'])}) ---")
        by_reason: dict[str, int] = {}
        for _, reason in data["junk"]:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        for reason, n in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    {n:4d}  {reason}")
        print("    run with --fix-junk to quarantine these")

    print()


def fix_junk(data: dict, vault: Path):
    if not data["junk"]:
        print("no junk found")
        return
    quarantine = vault.parent / f"vault-quarantine-{time.strftime('%Y%m%d-%H%M%S')}"
    moved = renamed = 0
    for path, reason in data["junk"]:
        rel = path.relative_to(vault)
        if reason == "double extension":
            # A real file with a broken name: fix it rather than quarantine,
            # unless the correct name is already taken.
            target = path.with_name(path.name[:-3])
            if not target.exists():
                path.rename(target)
                renamed += 1
                continue
        dest = quarantine / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        moved += 1
    print(f"renamed {renamed} file(s) to fix double extensions")
    print(f"moved {moved} file(s) to {quarantine}")
    print("nothing was deleted — review, then remove that folder when happy")


def api(register: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{register.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait_for(register: str, key: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"{register.rstrip('/')}/api/jobs/{key}", timeout=15) as r:
                job = json.loads(r.read())
            if job.get("state") != "running":
                return job.get("result") or {}
        except Exception:
            pass
        time.sleep(2)
    return {"status": "timeout"}


def merges(data: dict) -> list[tuple[list[str], str]]:
    convo = data["convo"]
    all_names = sorted(set(convo) | set(data["folders"]))
    plan = []
    for g in find_duplicates(all_names):
        counts = {n: convo.get(n, 0) for n in g}
        target = max(counts, key=lambda n: counts[n])
        sources = [n for n in g if n != target and convo.get(n, 0) > 0]
        if sources:
            plan.append((sources, target))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--register", default=DEFAULT_REGISTER)
    ap.add_argument("--fix-junk", action="store_true")
    ap.add_argument("--apply-titlecase", action="store_true",
                    help="rename project folders to TitleCase")
    ap.add_argument("--apply-claims", action="store_true",
                    help="rewrite project: fields that near-match a folder")
    ap.add_argument("--plan-merges", action="store_true")
    ap.add_argument("--apply-merges", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.exists():
        sys.exit(f"vault not found: {vault}")

    data = scan(vault)
    report(data, vault)

    rules = folder_rules(vault)
    report_rules(rules)

    if args.apply_titlecase:
        print("=== RENAMING FOLDERS TO TITLECASE ===")
        apply_titlecase(vault, rules)
        rules = folder_rules(vault)
    if args.apply_claims:
        print("=== REWRITING project: FIELDS ===")
        apply_claims(vault, rules)

    if args.fix_junk:
        print("=== FIXING JUNK ===")
        fix_junk(data, vault)
        data = scan(vault)

    plan = merges(data)
    if args.plan_merges or args.apply_merges:
        if not plan:
            print("no merges suggested")
            return
        print("=== MERGE PLAN ===")
        for sources, target in plan:
            print(f"    {', '.join(sources)}  →  {target}")
        print()

    if args.apply_merges:
        confirm = input("Apply these merges? Files move on disk. [yes/N] ")
        if confirm.strip().lower() != "yes":
            print("aborted")
            return
        for sources, target in plan:
            print(f"merging {sources} → {target} ...", end=" ", flush=True)
            try:
                api(args.register, "/api/merge",
                    {"sources": sources, "target": target})
                res = wait_for(args.register, f"merge:{target}")
                print(res.get("status", "?"),
                      f"({res.get('files', 0)} files)" if res.get("files") else "")
            except Exception as e:
                print(f"failed: {e}")
        print("\ndone — check the register UI, then let oikb resync")


if __name__ == "__main__":
    main()
