"""Project register — Flask app."""
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from apscheduler.schedulers.background import BackgroundScheduler
import markdown as _markdown

import register
import herald_status

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")
VAULT_NAME = os.environ.get("OBSIDIAN_VAULT_NAME", "Obsidian")
COMPRESS_MAX_MB = int(os.environ.get("COMPRESS_MAX_MB", "20"))


@app.template_filter("markdown")
def markdown_filter(text):
    return _markdown.markdown(text or "", extensions=["extra", "sane_lists"])


@app.template_global()
def obsidian_uri(rel_path: str) -> str:
    return f"obsidian://open?vault={quote(VAULT_NAME)}&file={quote(rel_path)}"


# ── background jobs ─────────────────────────────────────────────────
# Canonical generation reads handoffs only. Explicit legacy bootstrap may
# process larger reference material, so all generation still runs off-request.
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




def _job_progress(key, message):
    logger.info("job %s: %s", key, message)
    with _lock:
        if key in _jobs:
            _jobs[key]["progress"] = message
            _jobs[key]["progress_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

def _start(key, fn):
    with _lock:
        cur = _jobs.get(key)
        if cur and cur["state"] == "running":
            return jsonify({"state": "running", "key": key,
                            "started_at": cur["started_at"]}), 409
        _jobs[key] = {"state": "running", "key": key, "_t0": time.time(),
                      "started_at": datetime.now(timezone.utc)
                      .isoformat(timespec="seconds"), "result": None,
                      "progress": "queued"}
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


@app.route("/archive")
def archive_page():
    projects = [p for p in register.project_list() if p["archived"]]
    return render_template("archive.html", projects=projects)


@app.route("/p/<name>")
def detail(name):
    p = register.project(name)
    if not p:
        return redirect(url_for("index"))
    p = {**p, **register.runbook_info(name), **register.context_info(name)}
    return render_template("detail.html", p=p, statuses=register.STATUSES)



@app.route("/compress")
def compress_page():
    return render_template(
        "compress.html",
        backend=register.SUMMARY_BACKEND,
        model=(register.COMPRESS_MODEL if register.SUMMARY_BACKEND == "local"
               else register.GEMINI_MODEL),
        max_mb=COMPRESS_MAX_MB,
    )


# ── api ─────────────────────────────────────────────────────────────

@app.route("/api/compress", methods=["POST"])
def api_compress():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"status": "error", "reason": "select at least one file"}), 400
    allowed = {".md", ".markdown", ".txt"}
    docs, total = [], 0
    limit = COMPRESS_MAX_MB * 1024 * 1024
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in allowed:
            return jsonify({"status": "error",
                            "reason": f"unsupported file type: {f.filename}"}), 400
        raw = f.read()
        total += len(raw)
        if total > limit:
            return jsonify({"status": "error",
                            "reason": f"uploads exceed {COMPRESS_MAX_MB} MB limit"}), 413
        docs.append((Path(f.filename or "document.md").name,
                     raw.decode("utf-8", errors="replace")))
    mode = request.form.get("mode", "balanced").lower()
    try:
        target_tokens = max(1000, min(12000, int(request.form.get("target_tokens", "12000"))))
    except ValueError:
        target_tokens = 12000
    key = f"compress:{time.time_ns()}"
    logger.info("compress request key=%s files=%d bytes=%d profile=%s target=%d engine=deterministic",
                key, len(docs), total, mode, target_tokens)
    return _start(
        key,
        lambda: register.compress_documents(
            docs, mode=mode, target_tokens=target_tokens,
            progress=lambda msg: _job_progress(key, msg)))


@app.route("/api/summary/<name>", methods=["POST"])
def api_summary(name):
    full = request.json.get("full", False) if request.is_json else False
    # A correction is a cross-artifact transaction: status, CTX/2 and RUNBOOK
    # must not disagree after one has been refreshed.
    fn = (lambda: register.refresh_project(name, full=full)) if register.correction_propagation_needed(name) \
         else (lambda: register.generate_summary(name, full=full))
    return _start(f"summary:{name}", fn)


@app.route("/api/runbook/<name>", methods=["POST"])
def api_runbook(name):
    return _start(f"runbook:{name}", lambda: register.generate_runbook(name))


@app.route("/api/bootstrap/<name>", methods=["POST"])
def api_bootstrap(name):
    return _start(f"bootstrap:{name}", lambda: register.bootstrap_handoff(name))


@app.route("/api/context/<name>", methods=["GET", "POST"])
def api_context(name):
    if request.method == "POST":
        full = request.json.get("full", False) if request.is_json else False
        fn = (lambda: register.refresh_project(name, full=full)) if register.correction_propagation_needed(name) \
             else (lambda: register.generate_context(name, full=full))
        return _start(f"context:{name}", fn)
    p = register.project(name)
    if not p:
        return jsonify({"status": "error", "reason": "project not found"}), 404
    info = register.context_info(p["name"])
    if not info["has_context"]:
        return jsonify({"status": "error", "reason": "context not generated"}), 404
    headers = {}
    if request.args.get("download") == "1":
        headers["Content-Disposition"] = f'attachment; filename="{register.context_name(p["name"])}"'
    return Response(info["context"] + "\n", mimetype="text/plain", headers=headers)


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


@app.route("/api/tasks/<name>", methods=["POST"])
def api_task_add(name):
    body = request.json or {}
    r = register.add_task(name, body.get("text", ""), body.get("status", "todo"))
    return jsonify(r), (200 if r["status"] == "ok" else 400)


@app.route("/api/tasks/<name>/<task_id>", methods=["POST", "DELETE"])
def api_task(name, task_id):
    if request.method == "DELETE":
        r = register.delete_task(name, task_id)
    else:
        body = request.json or {}
        r = register.update_task(
            name, task_id,
            status=body.get("status") if "status" in body else None,
            text=body.get("text") if "text" in body else None,
        )
    return jsonify(r), (200 if r["status"] == "ok" else 400)


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
_PROMPT_DIR = Path(__file__).parent


def _slug_list() -> str:
    active = [p["name"] for p in register.project_list() if not p["archived"]]
    return "\n".join(f"  {n}" for n in active) or "  (no projects yet)"


def _prompt_text(kind: str = "handoff", project: str | None = None) -> str:
    """Two prompts, two jobs.

    handoff  — what changed this session; appended to a running record and
               folded into the project summary. Incremental.
    debrief  — what the project IS today; a standalone context document to
               paste at the start of a new chat. Supersedes rather than
               accumulates, so it carries no history.
    """
    fname = "debrief_prompt.md" if kind == "debrief" else "handoff_prompt.md"
    try:
        template = (_PROMPT_DIR / fname).read_text(encoding="utf-8")
    except OSError:
        return f"{fname} is missing from the container."

    if kind == "debrief":
        p = register.project(project) if project else None
        name = p["name"] if p else (project or "<project slug>")
        repo = (p.get("repo") if p else "") or \
            "(no repo recorded — set one on the project page)"
        return template.replace("<PROJECT>", name).replace("<REPO>", repo)

    return template.replace("<SLUG_LIST>", _slug_list())


@app.route("/prompt")
@app.route("/prompt/<kind>")
def prompt_page(kind: str = "handoff"):
    """Plain text so it can be curled, piped, or selected and copied.
    /prompt            session handoff, with current slugs
    /prompt/debrief?project=Name   full project debrief, scoped to one
    """
    if kind not in ("handoff", "debrief"):
        kind = "handoff"
    text = _prompt_text(kind, request.args.get("project"))
    return text, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/stats")
def api_stats():
    ps = register.project_list()
    return jsonify({
        "projects": len(ps),
        "active": len([p for p in ps if not p["archived"]]),
        "with_summary": len([p for p in ps if p["has_summary"]]),
        "with_context": len([p for p in ps if p.get("has_context")]),
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
# Historical AI conversations and other reference files are never an implicit
# fallback. Legacy material must be explicitly bootstrapped into a handoff.
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
            res = register.refresh_project(p["name"])
            logger.info("auto refresh %s → %s context=%s summary=%s runbook=%s",
                        p["name"], res.get("status"),
                        (res.get("context") or {}).get("status"),
                        (res.get("summary") or {}).get("status"),
                        (res.get("runbook") or {}).get("status"))
            if res.get("status") == "generated":
                done += 1
        except Exception:
            logger.exception("auto refresh failed for %s", p["name"])
    logger.info("auto summary run complete: %d generated, %d skipped "
                "(no handoff notes — explicit bootstrap required)",
                done, skipped_no_handoff)


def scheduled_synthesis():
    """Run the monthly whole-estate Gemini review in a child process."""
    script = Path(__file__).with_name("synthesise.py")
    cmd = [sys.executable, str(script), "--vault", str(register.VAULT_PATH)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception:
        logger.exception("monthly synthesis failed to start")
        return
    if proc.stdout.strip():
        logger.info("monthly synthesis stdout: %s", proc.stdout.strip())
    if proc.stderr.strip():
        logger.info("monthly synthesis stderr: %s", proc.stderr.strip())
    if proc.returncode:
        logger.error("monthly synthesis exited %d", proc.returncode)
    else:
        logger.info("monthly synthesis complete")


def scheduled_herald_export():
    """Publish the once-daily Register delta after refresh/synthesis jobs."""
    try:
        herald_status.export_status()
    except Exception:
        logger.exception("Herald status export failed")


def _enabled(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).lower() == "true"


_sched = BackgroundScheduler(timezone=os.environ.get("TZ", "Europe/London"))
_sched_jobs = 0

if _enabled("AUTO_SUMMARY", os.environ.get("WEEKLY_REFRESH", "true")):
    _hour = int(os.environ.get("AUTO_SUMMARY_HOUR", "3"))
    _sched.add_job(scheduled_refresh, "cron", hour=_hour, minute=0,
                   id="auto_summary", coalesce=True, max_instances=1)
    _sched_jobs += 1
    logger.info("auto summary scheduled (daily %02d:00, max %d per run)",
                _hour, AUTO_MAX)

if _enabled("MONTHLY_SYNTHESIS", "true"):
    _syn_hour = int(os.environ.get("MONTHLY_SYNTHESIS_HOUR", "4"))
    _sched.add_job(scheduled_synthesis, "cron", day=1, hour=_syn_hour, minute=0,
                   id="monthly_synthesis", coalesce=True, max_instances=1)
    _sched_jobs += 1
    logger.info("monthly synthesis scheduled (day 1 at %02d:00)", _syn_hour)

if _enabled("HERALD_STATUS_EXPORT", "true"):
    _hs_hour = int(os.environ.get("HERALD_STATUS_HOUR", "6"))
    _hs_minute = int(os.environ.get("HERALD_STATUS_MINUTE", "15"))
    _sched.add_job(scheduled_herald_export, "cron", hour=_hs_hour, minute=_hs_minute,
                   id="herald_status", coalesce=True, max_instances=1)
    _sched_jobs += 1
    logger.info("Herald status export scheduled (daily %02d:%02d)",
                _hs_hour, _hs_minute)

if _sched_jobs:
    _sched.start()

logger.info("register ready: vault=%s backend=%s",
            register.VAULT_PATH, register.SUMMARY_BACKEND)
