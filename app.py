"""Project register — Flask app."""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import markdown as _markdown

import register

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")
VAULT_NAME = os.environ.get("OBSIDIAN_VAULT_NAME", "Obsidian")


@app.template_filter("markdown")
def markdown_filter(text):
    return _markdown.markdown(text or "", extensions=["extra", "sane_lists"])


@app.template_global()
def obsidian_uri(rel_path: str) -> str:
    return f"obsidian://open?vault={quote(VAULT_NAME)}&file={quote(rel_path)}"


# ── background jobs ─────────────────────────────────────────────────
# Summaries take seconds from handoff docs but minutes from raw
# transcripts, so they never run inside a request.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run(key, fn):
    try:
        result, state = fn(), "done"
    except Exception as e:
        logger.exception("job %s failed", key)
        result, state = {"reason": str(e)}, "error"
    with _lock:
        _jobs[key].update(state=state, result=result,
                          elapsed_s=round(time.time() - _jobs[key]["_t0"], 1))


def _start(key, fn):
    with _lock:
        cur = _jobs.get(key)
        if cur and cur["state"] == "running":
            return jsonify({"state": "running", "key": key,
                            "started_at": cur["started_at"]}), 409
        _jobs[key] = {"state": "running", "key": key, "_t0": time.time(),
                      "started_at": datetime.now(timezone.utc)
                      .isoformat(timespec="seconds"), "result": None}
    threading.Thread(target=_run, args=(key, fn), daemon=True).start()
    return jsonify({"state": "running", "key": key}), 202


@app.route("/api/jobs")
def jobs():
    with _lock:
        return jsonify({k: dict(v) for k, v in _jobs.items()})


@app.route("/api/jobs/<path:key>")
def job(key):
    with _lock:
        j = _jobs.get(key)
    return (jsonify(dict(j)), 200) if j else (jsonify({"state": "unknown"}), 404)


# ── pages ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    projects = register.project_list()
    active = [p for p in projects if not p["archived"]]
    archived = [p for p in projects if p["archived"]]
    counts: dict[str, int] = {}
    for p in active:
        counts[p["status"] or "unset"] = counts.get(p["status"] or "unset", 0) + 1
    needs_handoff = [p for p in active if p["file_count"] and not p["handoff_count"]]
    return render_template("index.html", active=active, archived=archived,
                           counts=counts, statuses=register.STATUSES,
                           needs_handoff=needs_handoff,
                           unfiled=register.unfiled_groups(),
                           badly_named=[p for p in active if not p["name_ok"]])


@app.route("/p/<name>")
def detail(name):
    p = register.project(name)
    if not p:
        return redirect(url_for("index"))
    p = {**p, **register.runbook_info(name)}
    return render_template("detail.html", p=p, statuses=register.STATUSES)


# ── api ─────────────────────────────────────────────────────────────
@app.route("/api/summary/<name>", methods=["POST"])
def api_summary(name):
    full = request.json.get("full", False) if request.is_json else False
    return _start(f"summary:{name}",
                  lambda: register.generate_summary(name, full=full))


@app.route("/api/runbook/<name>", methods=["POST"])
def api_runbook(name):
    return _start(f"runbook:{name}", lambda: register.generate_runbook(name))


@app.route("/api/status/<name>", methods=["POST"])
def api_status(name):
    r = register.set_status(name, (request.json or {}).get("status", ""))
    return jsonify(r), (200 if r["status"] == "ok" else 400)


@app.route("/api/archive/<name>", methods=["POST"])
def api_archive(name):
    r = register.set_archived(name, (request.json or {}).get("archived", True))
    return jsonify(r), (200 if r["status"] == "ok" else 500)


@app.route("/api/repo/<name>", methods=["POST"])
def api_repo(name):
    r = register.set_repo(name, (request.json or {}).get("repo", ""))
    return jsonify(r), (200 if r["status"] == "ok" else 500)


@app.route("/api/rename/<name>", methods=["POST"])
def api_rename(name):
    new = (request.json or {}).get("new", "")
    return _start(f"rename:{name}", lambda: register.rename(name, new))


@app.route("/api/merge", methods=["POST"])
def api_merge():
    d = request.json or {}
    target = d.get("target", "")
    return _start(f"merge:{target}",
                  lambda: register.merge(d.get("sources") or [], target))


@app.route("/api/unfiled")
def api_unfiled():
    return jsonify(register.unfiled_groups())


@app.route("/api/file", methods=["POST"])
def api_file():
    """Resolve an unfiled claim: assign its files to an existing project,
    or promote the claim into a new one. Body:
    {"claimed": "...", "target": "...", "create": false}"""
    d = request.json or {}
    r = register.file_claim(d.get("claimed", ""), d.get("target", ""),
                            bool(d.get("create", False)))
    return jsonify(r), (200 if r.get("status") == "ok" else 400)


@app.route("/api/create", methods=["POST"])
def api_create():
    r = register.create_project((request.json or {}).get("name", ""))
    return jsonify(r), (200 if r["status"] == "ok" else 400)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    register.invalidate()
    return jsonify({"status": "ok", "projects": len(register.all_projects())})


# ── handoff prompt ──────────────────────────────────────────────────
# Serves the end-of-session prompt with the CURRENT project slugs baked
# in. The two failure modes we actually hit — a model inventing a slug
# (which spawned nine homelab-* projects) and drifting capitalisation
# (which collided on the Windows Syncthing peer) — both came from the
# model guessing. Give it the real list and it can't.
_PROMPT_PATH = Path(__file__).parent / "handoff_prompt.md"


def _prompt_text() -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "handoff_prompt.md is missing from the container."
    active = [p["name"] for p in register.project_list() if not p["archived"]]
    listing = "\n".join(f"  {n}" for n in active) or "  (no projects yet)"
    return template.replace("<SLUG_LIST>", listing)


@app.route("/prompt")
def prompt_page():
    """Plain text so it can be curled, piped, or selected and copied."""
    return _prompt_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/stats")
def api_stats():
    ps = register.project_list()
    return jsonify({
        "projects": len(ps),
        "active": len([p for p in ps if not p["archived"]]),
        "with_summary": len([p for p in ps if p["has_summary"]]),
        "files": sum(p["file_count"] for p in ps),
        "handoffs": sum(p["handoff_count"] for p in ps),
        "summary_backend": register.SUMMARY_BACKEND,
    })


# ── scheduled refresh ───────────────────────────────────────────────
# Runs nightly rather than weekly. A project with nothing new since its
# summarised_through mark returns "fresh" without calling the model at
# all, so a quiet night costs nothing — and a handoff note written on
# Tuesday shows up Wednesday instead of the following Sunday.
#
# Only projects that HAVE handoff notes are refreshed automatically.
# Transcript fallback is expensive (a 170KB export is minutes of CPU
# prompt processing) and lower quality, so it stays a deliberate choice
# you make from the project page, never something that happens to thirty
# projects at 3am unasked.
AUTO_MAX = int(os.environ.get("AUTO_SUMMARY_MAX_PER_RUN", "5"))


def scheduled_refresh():
    register.invalidate()
    done = skipped_no_handoff = 0
    for p in register.project_list():
        if p["archived"] or not p["file_count"]:
            continue
        if not p["handoff_count"]:
            skipped_no_handoff += 1
            continue
        if done >= AUTO_MAX:
            logger.info("auto-summary cap (%d) reached; remainder next run",
                        AUTO_MAX)
            break
        try:
            res = register.generate_summary(p["name"])
            logger.info("auto summary %s → %s", p["name"], res["status"])
            if res.get("status") == "generated":
                done += 1          # only generations count toward the cap
        except Exception:
            logger.exception("auto summary failed for %s", p["name"])
    logger.info("auto summary run complete: %d generated, %d skipped "
                "(no handoff notes — use the project page to summarise those)",
                done, skipped_no_handoff)


if os.environ.get("AUTO_SUMMARY", os.environ.get("WEEKLY_REFRESH", "true")).lower() == "true":
    _hour = int(os.environ.get("AUTO_SUMMARY_HOUR", "3"))
    sched = BackgroundScheduler(timezone=os.environ.get("TZ", "Europe/London"))
    sched.add_job(scheduled_refresh, "cron", hour=_hour, id="auto_summary")
    sched.start()
    logger.info("auto summary scheduled (daily %02d:00, max %d per run)",
                _hour, AUTO_MAX)

logger.info("register ready: vault=%s backend=%s",
            register.VAULT_PATH, register.SUMMARY_BACKEND)
