#!/usr/bin/env python3
"""secret-scan.py — audit project folders for secrets and personal data
before putting them on GitHub.

Designed for the specific question "is it safe to push this?", so it does
three things generic scanners usually don't:

  * It checks whether each finding sits in a file git would actually
    commit. A key in a gitignored .env is a very different risk from the
    same key in docker-compose.yml.
  * It searches git history for each secret it finds. Deleting a key from
    the working tree does nothing if it is still in an old commit.
  * It looks for personal identifiers (name, email, home paths, internal
    IPs, postcode) as well as credentials, because those are what quietly
    de-anonymise a "clean" public repo.

Usage:
    ./secret-scan.py ~/dockers/*                 # scan several projects
    ./secret-scan.py ~/dockers/herald --verbose  # show every finding
    ./secret-scan.py ~/dockers/* --json > audit.json
    ./secret-scan.py ~/dockers/foo --no-history  # skip git log search

Exit codes: 0 clean, 1 findings that block a push, 2 warnings only.

Allowlist false positives by adding a .secretscanignore file to a project,
one substring per line; any finding whose snippet contains it is dropped.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ── what counts as a secret ─────────────────────────────────────────
# (name, regex, severity)  severity: CRITICAL blocks a push, WARN is
# judgement, INFO is context.
RULES = [
    # Cloud and model-provider credentials
    ("Google API key",      r"AIza[0-9A-Za-z_\-]{35}", "CRITICAL"),
    ("Google OAuth id",     r"[0-9]+-[0-9a-z_]{32}\.apps\.googleusercontent\.com", "WARN"),
    ("OpenAI key",          r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", "CRITICAL"),
    ("Anthropic key",       r"sk-ant-[A-Za-z0-9_\-]{20,}", "CRITICAL"),
    ("HuggingFace token",   r"hf_[A-Za-z0-9]{30,}", "CRITICAL"),
    ("AWS access key",      r"(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}", "CRITICAL"),
    ("AWS secret key",      r"(?i)aws_secret[_a-z]*\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}", "CRITICAL"),
    ("GitHub token",        r"gh[pousr]_[A-Za-z0-9]{36,}", "CRITICAL"),
    ("GitHub fine-grained", r"github_pat_[A-Za-z0-9_]{50,}", "CRITICAL"),
    ("GitLab token",        r"glpat-[A-Za-z0-9_\-]{20,}", "CRITICAL"),
    ("Slack token",         r"xox[abprs]-[A-Za-z0-9\-]{10,}", "CRITICAL"),
    ("Slack webhook",       r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+", "CRITICAL"),
    ("Discord webhook",     r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_\-]+", "CRITICAL"),
    ("Telegram bot token",  r"[0-9]{8,10}:AA[A-Za-z0-9_\-]{33}", "CRITICAL"),
    ("Stripe live key",     r"sk_live_[A-Za-z0-9]{20,}", "CRITICAL"),
    ("Twilio SID",          r"AC[a-f0-9]{32}", "WARN"),
    ("SendGrid key",        r"SG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "CRITICAL"),
    ("Mailgun key",         r"key-[a-f0-9]{32}", "CRITICAL"),
    ("npm token",           r"npm_[A-Za-z0-9]{36}", "CRITICAL"),
    ("PyPI token",          r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}", "CRITICAL"),
    ("Cloudflare token",    r"(?i)cloudflare[_a-z]*token\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{30,}", "CRITICAL"),

    # Keys and certificates
    ("Private key block",   r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE" + r" KEY", "CRITICAL"),
    ("SSH private key",     r"(?m)^-----BEGIN OPENSSH PRIVATE" + r" KEY-----", "CRITICAL"),
    ("JWT",                 r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "WARN"),

    # Credentials in config and code
    ("Password assignment", r"(?i)\b(?:password|passwd|pwd)\s*[=:]\s*['\"]?(?!\s*[\"']?\s*$)(?!\$\{)(?!<)(?!change[_-]?me)(?!your[_-])(?!xxx)[^\s'\"#$]{4,}", "WARN"),
    ("Secret assignment",   r"(?i)\b(?:secret|api[_-]?key|apikey|auth[_-]?token|access[_-]?token|private[_-]?key)\s*[=:]\s*['\"]?(?!\s*[\"']?\s*$)(?!\$\{)(?!<)(?!change[_-]?me)(?!your[_-])(?!xxx)[^\s'\"#$]{8,}", "WARN"),
    ("DB connection string", r"(?i)(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/]+:[^@\s]+@", "CRITICAL"),
    ("Basic auth URL",      r"https?://[^:/\s]+:[^@/\s]+@[^\s/]+", "CRITICAL"),
    ("Authorization header", r"(?i)authorization\s*[=:]\s*['\"]?(?:bearer|basic)\s+[A-Za-z0-9_\-\.=+/]{16,}", "CRITICAL"),
]

# Filenames that should essentially never be committed
BAD_FILENAMES = [
    (r"^\.env$", "env file", "WARN"),
    (r"^\.env\.(?!example|sample|template)", "env file", "WARN"),
    (r"^stack\.env$", "env file", "WARN"),
    (r"^id_(rsa|dsa|ecdsa|ed25519)$", "SSH private key", "CRITICAL"),
    (r"\.pem$", "certificate/key", "CRITICAL"),
    (r"\.p12$|\.pfx$|\.jks$", "keystore", "CRITICAL"),
    (r"\.key$", "key file", "CRITICAL"),
    (r"\.kdbx?$", "password database", "CRITICAL"),
    (r"^\.htpasswd$", "htpasswd", "CRITICAL"),
    (r"^\.netrc$|^_netrc$", "netrc credentials", "CRITICAL"),
    (r"^\.pgpass$", "postgres password file", "CRITICAL"),
    (r"^credentials(\.json)?$|^service[_-]account.*\.json$", "cloud credentials", "CRITICAL"),
    (r"\.sqlite3?$|\.db$", "database file", "WARN"),
    (r"\.bak$|\.backup$|~$", "backup file", "INFO"),
    (r"^\.DS_Store$", "macOS metadata", "INFO"),
    (r"\.ovpn$", "VPN profile", "CRITICAL"),
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
             ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
             "site-packages", ".cache", "vendor"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".pdf",
            ".zip", ".gz", ".tar", ".xz", ".bz2", ".7z", ".mp3", ".mp4",
            ".flac", ".opus", ".wav", ".woff", ".woff2", ".ttf", ".otf",
            ".pyc", ".so", ".o", ".bin", ".class", ".jar", ".whl"}
MAX_FILE_BYTES = 2_000_000
SEV_ORDER = {"CRITICAL": 0, "WARN": 1, "INFO": 2}


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = defaultdict(int)
    for ch in s:
        counts[ch] += 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def personal_rules(name: str, email: str, extra: list[str]) -> list:
    """Identifiers that de-anonymise a repo without being secrets."""
    rules = [
        ("Home path",        r"/home/[a-z][a-z0-9_\-]{2,}/", "WARN"),
        ("Windows user path", r"[Cc]:\\Users\\[A-Za-z0-9_\- ]+", "WARN"),
        ("Private IP",       r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", "INFO"),
        ("Email address",    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "WARN"),
        ("UK postcode",      r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", "WARN"),
        ("UK phone",         r"\b(?:\+44\s?7\d{3}|\(?07\d{3}\)?)\s?\d{3}\s?\d{3}\b", "WARN"),
        ("Tailscale/VPN host", r"\b[a-z0-9\-]+\.(?:ts\.net|tailscale\.net)\b", "INFO"),
    ]
    if name:
        for part in [p for p in re.split(r"\s+", name) if len(p) > 2]:
            rules.append((f"Personal name ({part})",
                          r"(?i)\b" + re.escape(part) + r"\b", "WARN"))
    if email:
        rules.append(("Personal email", r"(?i)" + re.escape(email), "WARN"))
    for term in extra:
        rules.append((f"Custom term ({term})",
                      r"(?i)\b" + re.escape(term) + r"\b", "WARN"))
    return rules


def redact(s: str, keep: int = 6) -> str:
    s = s.strip()
    if len(s) <= keep:
        return s[:keep] + "…"
    return s[:keep] + "…" + f"[{len(s)} chars]"


def git_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse",
                              "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        return Path(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


def ignored_paths(root: Path, paths: list[Path]) -> set[str]:
    """Which of these paths git would NOT commit."""
    if not paths:
        return set()
    try:
        rels = [str(p.relative_to(root)) for p in paths]
        out = subprocess.run(["git", "-C", str(root), "check-ignore", "--stdin"],
                             input="\n".join(rels), capture_output=True,
                             text=True, timeout=30)
        return {line.strip() for line in out.stdout.splitlines() if line.strip()}
    except Exception:
        return set()


def in_history(root: Path, needle: str) -> str | None:
    """Was this exact string ever committed? Deleting it from the working
    tree is not enough — history keeps it."""
    if len(needle) < 12:
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "--all",
                              "--oneline", "-S", needle, "--max-count=3"],
                             capture_output=True, text=True, timeout=45)
        first = out.stdout.strip().splitlines()
        return first[0] if first else None
    except Exception:
        return None


def scan_project(proj: Path, prules: list, do_history: bool,
                 entropy_check: bool) -> dict:
    root = git_root(proj)
    has_git = root is not None and root == proj
    allow: list[str] = []
    ai = proj / ".secretscanignore"
    if ai.exists():
        allow = [l.strip() for l in ai.read_text(errors="replace").splitlines()
                 if l.strip() and not l.startswith("#")]

    findings, files = [], []
    for path in proj.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)

    ignored = ignored_paths(proj, files) if has_git else set()

    def is_ignored(p: Path) -> bool:
        try:
            return str(p.relative_to(proj)) in ignored
        except ValueError:
            return False

    for path in files:
        rel = str(path.relative_to(proj))
        ign = is_ignored(path)

        for pattern, label, sev in BAD_FILENAMES:
            if re.search(pattern, path.name):
                findings.append({
                    "file": rel, "line": 0, "rule": f"Sensitive file: {label}",
                    "severity": "INFO" if ign and sev != "CRITICAL" else sev,
                    "snippet": path.name, "gitignored": ign, "history": None})

        if path.suffix.lower() in SKIP_EXT:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 4000:
                continue
            for label, pattern, sev in RULES + prules:
                for m in re.finditer(pattern, line):
                    hit = m.group(0)
                    if any(a in hit or a in line for a in allow):
                        continue
                    findings.append({
                        "file": rel, "line": lineno, "rule": label,
                        "severity": sev, "snippet": redact(hit),
                        "raw": hit, "gitignored": ign, "history": None})

            if entropy_check:
                for m in re.finditer(
                        r"(?i)\b([A-Z][A-Z0-9_]{3,})\s*[=:]\s*['\"]?([A-Za-z0-9+/_\-]{24,})['\"]?", line):
                    val = m.group(2)
                    if entropy(val) > 4.2 and not val.startswith("${"):
                        findings.append({
                            "file": rel, "line": lineno,
                            "rule": f"High-entropy value ({m.group(1)})",
                            "severity": "WARN", "snippet": redact(val),
                            "raw": val, "gitignored": ign, "history": None})

    # Dedupe on (file, line, rule, snippet)
    seen, deduped = set(), []
    for f in findings:
        k = (f["file"], f["line"], f["rule"], f["snippet"])
        if k not in seen:
            seen.add(k)
            deduped.append(f)
    findings = deduped

    if has_git and do_history:
        checked: dict[str, str | None] = {}
        for f in findings:
            raw = f.get("raw")
            if not raw or f["severity"] == "INFO":
                continue
            if raw not in checked:
                checked[raw] = in_history(proj, raw)
            f["history"] = checked[raw]

    for f in findings:
        f.pop("raw", None)

    return {"project": proj.name, "path": str(proj), "git": has_git,
            "files_scanned": len(files), "findings": findings}


def print_report(res: dict, verbose: bool):
    findings = sorted(res["findings"],
                      key=lambda f: (SEV_ORDER[f["severity"]], f["file"], f["line"]))
    crit = [f for f in findings if f["severity"] == "CRITICAL"]
    warn = [f for f in findings if f["severity"] == "WARN"]
    info = [f for f in findings if f["severity"] == "INFO"]

    # A finding matters most when git would actually commit it.
    exposed = [f for f in crit + warn if not f["gitignored"]]
    committed = [f for f in findings if f["history"]]

    git_note = "git repo" if res["git"] else "no git repo yet"
    print(f"\n{'='*70}\n{res['project']}  ({git_note}, "
          f"{res['files_scanned']} files)\n{'='*70}")

    if not findings:
        print("  clean — nothing found")
        return

    print(f"  {len(crit)} critical, {len(warn)} warning, {len(info)} info")
    if res["git"]:
        print(f"  {len(exposed)} would be committed (not gitignored)")
        if committed:
            print(f"  {len(committed)} ALREADY IN GIT HISTORY — rotation "
                  f"required, deletion is not enough")

    shown = findings if verbose else (crit + warn)[:40]
    for f in shown:
        flag = ""
        if f["gitignored"]:
            flag = " [gitignored]"
        elif res["git"]:
            flag = " [WOULD COMMIT]"
        hist = f"  <-- in history: {f['history']}" if f["history"] else ""
        loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        print(f"    {f['severity']:8s} {f['rule']:32s} {loc}{flag}")
        print(f"             {f['snippet']}{hist}")
    if not verbose and len(findings) > len(shown):
        print(f"    ... and {len(findings) - len(shown)} more (--verbose)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="project directories to scan")
    ap.add_argument("--name", default="", help="your name, to flag in files")
    ap.add_argument("--email", default="", help="your email, to flag")
    ap.add_argument("--term", action="append", default=[],
                    help="extra term to flag (repeatable)")
    ap.add_argument("--no-history", action="store_true",
                    help="skip searching git history (faster)")
    ap.add_argument("--no-entropy", action="store_true",
                    help="skip high-entropy value detection")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    name, email = args.name, args.email
    if not name:
        try:
            name = subprocess.run(["git", "config", "--get", "user.name"],
                                  capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        except Exception:
            pass
    if not email:
        try:
            email = subprocess.run(["git", "config", "--get", "user.email"],
                                   capture_output=True, text=True,
                                   timeout=5).stdout.strip()
        except Exception:
            pass

    prules = personal_rules(name, email, args.term)
    results = []
    for raw in args.paths:
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            continue
        results.append(scan_project(p, prules, not args.no_history,
                                    not args.no_entropy))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print_report(r, args.verbose)

        total_c = sum(len([f for f in r["findings"]
                           if f["severity"] == "CRITICAL"]) for r in results)
        total_e = sum(len([f for f in r["findings"]
                           if f["severity"] in ("CRITICAL", "WARN")
                           and not f["gitignored"]]) for r in results)
        total_h = sum(len([f for f in r["findings"] if f["history"]])
                      for r in results)
        print(f"\n{'='*70}")
        print(f"TOTAL: {len(results)} project(s), {total_c} critical, "
              f"{total_e} committable, {total_h} in history")
        if total_h:
            print("\nAnything already in git history must be ROTATED, not "
                  "deleted — rewriting history does not help once a repo "
                  "has been pushed or shared.")
        if total_e:
            print("\nBefore pushing: move secrets into a gitignored .env and "
                  "reference them as ${VAR} in committed files.")
        print()

    worst = 0
    for r in results:
        for f in r["findings"]:
            if f["severity"] == "CRITICAL" and not f["gitignored"]:
                worst = max(worst, 2)
            elif f["severity"] in ("CRITICAL", "WARN"):
                worst = max(worst, 1)
    sys.exit(1 if worst == 2 else (2 if worst == 1 else 0))


if __name__ == "__main__":
    main()
