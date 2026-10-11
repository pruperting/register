#!/usr/bin/env python3
"""secretscan.py — find credentials and personal data before publishing.

No dependencies. Scans a working tree and, optionally, the whole git
history — because a secret removed from the current files is still in the
history, and pushing that publishes it just as surely.

    ./secretscan.py ~/dockers/mixdlr              # one project
    ./secretscan.py ~/dockers --all               # every project under a dir
    ./secretscan.py ~/dockers/mixdlr --history    # include git history
    ./secretscan.py ~/dockers/mixdlr --json       # machine-readable
    ./secretscan.py --install-hook ~/dockers/mixdlr   # pre-commit hook

Exit codes: 0 clean, 1 CRITICAL findings, 2 only WARN/INFO findings.
So `secretscan.py . && git push` refuses to push on a critical hit.

Findings are ranked:
  CRITICAL  a real credential — rotate it, don't just delete it
  WARN      probably a credential, or a private key path
  INFO      personal data: names, emails, home paths, internal IPs

Tune the personal-data rules with --me / --email / --domain, or leave the
defaults, which pick up the current username and hostname.
"""
import argparse
import getpass
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

# ── what not to bother reading ──────────────────────────────────────
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".cache", "site-packages", ".terraform", "vendor",
}
SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".mp3", ".mp4", ".flac", ".opus", ".wav", ".avi", ".mkv", ".m4a",
    ".zip", ".gz", ".xz", ".bz2", ".tar", ".7z", ".rar",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pyc", ".pyo", ".so", ".o", ".a", ".bin", ".dat", ".db", ".sqlite",
    ".sqlite3", ".lock", ".pack", ".idx",
}
MAX_BYTES = 4_000_000

# Values that look like secrets but are obviously placeholders.
PLACEHOLDER = re.compile(
    r"^\s*($|-$|null|none|true|false|\d+$"
    r"|change[-_ ]?me|your[-_ ]?|example|sample|dummy|placeholder|redacted"
    r"|xxx+|\.\.\.|test[-_]?key|foo|bar|secret|password|token|api[-_]?key"
    r"|\$\{|\{\{|<|%\(|\*\*\*)", re.I)


def is_placeholder(value: str) -> bool:
    v = (value or "").strip().strip("'\"")
    if not v or len(v) < 6:
        return True
    return bool(PLACEHOLDER.match(v))


def shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# ── rules ───────────────────────────────────────────────────────────
# (name, severity, compiled regex, group holding the secret, note)
RULES = [
    ("Google / Gemini API key", "CRITICAL",
     re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0,
     "Google AI Studio / Cloud key"),
    ("AWS access key id", "CRITICAL",
     re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA|A3T[A-Z0-9])[A-Z0-9]{16}\b"), 0, ""),
    ("AWS secret access key", "CRITICAL",
     re.compile(r"(?i)aws[^\n]{0,30}?(?:secret|private)[^\n]{0,30}?"
                r"['\"]([A-Za-z0-9/+=]{40})['\"]"), 1, ""),
    ("GitHub token", "CRITICAL",
     re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b"), 0, ""),
    ("GitHub fine-grained PAT", "CRITICAL",
     re.compile(r"\bgithub_pat_[0-9a-zA-Z_]{60,}\b"), 0, ""),
    ("OpenAI / Anthropic key", "CRITICAL",
     re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}\b"), 0, ""),
    ("Slack token", "CRITICAL",
     re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"), 0, ""),
    ("Slack webhook", "CRITICAL",
     re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"), 0, ""),
    ("Discord webhook", "CRITICAL",
     re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[\w\-]{20,}"), 0, ""),
    ("Telegram bot token", "CRITICAL",
     re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,45}\b"), 0, ""),
    ("Stripe key", "CRITICAL",
     re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{20,}\b"), 0, ""),
    ("SendGrid key", "CRITICAL",
     re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{30,}\b"), 0, ""),
    ("Mailgun key", "CRITICAL",
     re.compile(r"\bkey-[0-9a-f]{32}\b"), 0, ""),
    ("Twilio SID/token", "CRITICAL",
     re.compile(r"\bAC[0-9a-f]{32}\b|\bSK[0-9a-f]{32}\b"), 0, ""),
    ("Private key block", "CRITICAL",
     re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY"), 0,
     "an actual key file or an inlined key"),
    ("JWT", "WARN",
     re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}"
                r"\.[A-Za-z0-9_\-]{8,}\b"), 0,
     "may embed credentials or personal claims"),
    ("Credentials in URL", "CRITICAL",
     re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]{1,20}://"
                r"([^\s:/@'\"]{2,}):([^\s:/@'\"]{2,})@"), 0,
     "user:password embedded in a connection string"),
    ("htpasswd hash", "WARN",
     re.compile(r"^[\w.\-]{1,32}:\$(?:apr1|2[aby]|5|6)\$[^\s]{10,}", re.M), 0, ""),
    ("Basic auth header", "WARN",
     re.compile(r"(?i)authorization\s*[:=]\s*['\"]?Basic\s+[A-Za-z0-9+/=]{12,}"), 0, ""),
    ("Generic secret assignment", "WARN",
     re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|"
                r"access[_-]?token|auth[_-]?token|private[_-]?key|client[_-]?secret)"
                r"\s*[:=]\s*['\"]?([^\s'\"#;,}\)]{8,})"), 1, ""),
]

PERSONAL = [
    ("Email address", re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("UK phone number", re.compile(
        r"\b(?:\+44\s?7\d{3}|\(?07\d{3}\)?)[\s.\-]?\d{3}[\s.\-]?\d{3}\b")),
    ("Private IPv4", re.compile(
        r"\b(?:192\.168\.\d{1,3}\.\d{1,3}"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("Tailscale IP", re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])"
                                r"\.\d{1,3}\.\d{1,3}\b")),
    ("MAC address", re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")),
    ("Home directory path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]{2,}")),
]

# Files whose mere presence is worth flagging.
RISKY_NAMES = re.compile(
    r"^(?:\.env(?:\..+)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa|id_ed25519|"
    r"id_ecdsa|\.netrc|\.pgpass|htpasswd|\.htpasswd|credentials|"
    r"service[-_]?account.*\.json|.*\.keystore|.*\.jks)$", re.I)
RISKY_SAFE = re.compile(r"\.(example|sample|template|dist)$", re.I)


def mask(s: str, keep: int = 4) -> str:
    s = s.strip().strip("'\"")
    if len(s) <= keep + 2:
        return "*" * len(s)
    return f"{s[:keep]}{'*' * min(12, len(s) - keep - 2)}{s[-2:]}"


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in SKIP_EXT:
                continue
            try:
                if p.stat().st_size > MAX_BYTES or p.is_symlink():
                    continue
            except OSError:
                continue
            yield p


def scan_text(text: str, where: str, personal_rules, findings: list,
              is_example: bool):
    for name, sev, rx, grp, note in RULES:
        for m in rx.finditer(text):
            captured = bool(grp and m.lastindex)
            value = m.group(grp) if captured else m.group(0)
            if captured and is_placeholder(value):
                continue
            # An example/template file may legitimately show the shape of a
            # secret; only high-confidence patterns still count there.
            if is_example and sev != "CRITICAL":
                continue
            if name == "Generic secret assignment":
                v = value.strip().strip("'\"")
                # Low-entropy short strings here are usually config, not keys.
                if len(v) < 12 and shannon(v) < 3.0:
                    continue
            line = text[:m.start()].count("\n") + 1
            findings.append({
                "severity": sev, "rule": name, "where": where,
                "line": line, "match": mask(value), "note": note,
            })
    for name, rx in personal_rules:
        seen = set()
        for m in rx.finditer(text):
            v = m.group(0)
            if v in seen:
                continue
            seen.add(v)
            line = text[:m.start()].count("\n") + 1
            findings.append({
                "severity": "INFO", "rule": name, "where": where,
                "line": line, "match": v, "note": "",
            })


def scan_tree(root: Path, personal_rules) -> list:
    findings = []
    for p in iter_files(root):
        rel = str(p.relative_to(root))
        base = p.name
        if RISKY_NAMES.match(base) and not RISKY_SAFE.search(base):
            findings.append({
                "severity": "WARN", "rule": "Sensitive file present",
                "where": rel, "line": 0, "match": base,
                "note": "must be gitignored; check `git check-ignore -v`",
            })
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        scan_text(text, rel, personal_rules, findings,
                  bool(RISKY_SAFE.search(base)) or ".example" in base)
    return findings


def scan_history(root: Path, personal_rules) -> list:
    """Secrets committed and later deleted are still published on push."""
    if not (root / ".git").exists():
        return []
    try:
        blob = subprocess.run(
            ["git", "-C", str(root), "log", "--all", "-p", "--no-color",
             "--diff-filter=AM", "-U0"],
            capture_output=True, text=True, timeout=300, errors="replace")
    except (subprocess.SubprocessError, OSError) as e:
        return [{"severity": "INFO", "rule": "History scan failed",
                 "where": ".git", "line": 0, "match": str(e)[:60], "note": ""}]
    findings = []
    scan_text(blob.stdout, "GIT HISTORY", personal_rules, findings, False)
    for f in findings:
        f["line"] = 0
        if f["severity"] == "CRITICAL":
            f["note"] = "in git history — rewriting history is not enough, ROTATE"
    return findings


def check_gitignore(root: Path) -> list:
    """Verify the things that must be ignored actually are."""
    if not (root / ".git").exists():
        return []
    out = []
    for name in (".env", "stack.env", "secrets", "id_rsa"):
        p = root / name
        if not p.exists():
            continue
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", name],
                           capture_output=True)
        if r.returncode != 0:
            out.append({
                "severity": "CRITICAL", "rule": "Sensitive file NOT gitignored",
                "where": name, "line": 0, "match": name,
                "note": "add to .gitignore before committing",
            })
    return out


HOOK = """#!/bin/sh
# installed by secretscan.py
exec "{script}" "$(git rev-parse --show-toplevel)" --quiet || {{
  echo "secretscan: commit blocked. Run '{script} .' for detail." >&2
  exit 1
}}
"""


def install_hook(root: Path):
    hooks = root / ".git" / "hooks"
    if not hooks.exists():
        sys.exit(f"{root} is not a git repository")
    target = hooks / "pre-commit"
    target.write_text(HOOK.format(script=str(Path(__file__).resolve())))
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    print(f"pre-commit hook installed: {target}")


def report(findings: list, root: Path, quiet: bool) -> int:
    order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["where"], f["line"]))
    crit = [f for f in findings if f["severity"] == "CRITICAL"]
    warn = [f for f in findings if f["severity"] == "WARN"]
    info = [f for f in findings if f["severity"] == "INFO"]

    if not quiet:
        print(f"\n=== {root} ===")
        for label, group in (("CRITICAL", crit), ("WARN", warn), ("INFO", info)):
            if not group:
                continue
            print(f"\n{label} ({len(group)})")
            shown = {}
            for f in group:
                # Collapse repetitive INFO noise to a few examples per rule.
                shown.setdefault(f["rule"], 0)
                shown[f["rule"]] += 1
                if label == "INFO" and shown[f["rule"]] > 5:
                    continue
                loc = f"{f['where']}:{f['line']}" if f["line"] else f["where"]
                note = f"  — {f['note']}" if f["note"] else ""
                print(f"  [{f['rule']}] {loc}\n      {f['match']}{note}")
            for rule, n in shown.items():
                if label == "INFO" and n > 5:
                    print(f"  ... {n - 5} more [{rule}]")
        if not findings:
            print("  clean")
        print()

    if crit:
        if quiet:
            print(f"secretscan: {len(crit)} CRITICAL finding(s) in {root}")
        return 1
    return 2 if warn or info else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--all", action="store_true",
                    help="treat PATH as a parent of many projects")
    ap.add_argument("--history", action="store_true",
                    help="also scan the full git history")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="only report criticals; for hooks")
    ap.add_argument("--no-personal", action="store_true",
                    help="skip emails, IPs, home paths etc")
    ap.add_argument("--me", default=None, help="your username")
    ap.add_argument("--name", default=None, help="your real name")
    ap.add_argument("--install-hook", metavar="REPO")
    args = ap.parse_args()

    if args.install_hook:
        install_hook(Path(args.install_hook).expanduser().resolve())
        return

    personal_rules = [] if args.no_personal else list(PERSONAL)
    if not args.no_personal:
        me = args.me or getpass.getuser()
        personal_rules.append(("Username", re.compile(rf"\b{re.escape(me)}\b")))
        host = socket.gethostname()
        if host and len(host) > 3:
            personal_rules.append(
                ("Hostname", re.compile(rf"\b{re.escape(host)}\b", re.I)))
        if args.name:
            personal_rules.append(
                ("Real name", re.compile(re.escape(args.name), re.I)))

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        sys.exit(f"not found: {root}")

    targets = ([d for d in sorted(root.iterdir())
                if d.is_dir() and d.name not in SKIP_DIRS]
               if args.all else [root])

    worst, all_findings = 0, {}
    for t in targets:
        findings = scan_tree(t, personal_rules) + check_gitignore(t)
        if args.history:
            findings += scan_history(t, personal_rules)
        all_findings[str(t)] = findings
        if not args.json:
            worst = max(worst, report(findings, t, args.quiet))
        else:
            crit = any(f["severity"] == "CRITICAL" for f in findings)
            worst = max(worst, 1 if crit else (2 if findings else 0))

    if args.json:
        print(json.dumps(all_findings, indent=2))
    elif args.all and not args.quiet:
        tot = sum(len(v) for v in all_findings.values())
        crit = sum(1 for v in all_findings.values()
                   for f in v if f["severity"] == "CRITICAL")
        print(f"=== {len(targets)} project(s), {tot} finding(s), "
              f"{crit} critical ===")
    sys.exit(worst)


if __name__ == "__main__":
    main()
