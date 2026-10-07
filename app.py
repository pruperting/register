"""Project register — Flask app."""
import logging
import json
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
import checkpoints

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
    register.invalidate()
    for item in register.project_list():
        if not item["archived"] and item["handoff_count"]:
            register.refresh_project(item["name"])
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
    result = register.refresh_project(name)
    p = register.project(name)
    p = {**p, "checkpoint_result": result, **register.context_info(name)}
    return render_template("detail.html", p=p, statuses=register.STATUSES)



@app.route("/compress")
def compress_page():
    return render_template(
        "compress.html",
        backend="deterministic",
        model="none",
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
    return _start(f"checkpoint:{name}", lambda: register.refresh_project(name))

@app.route("/api/runbook/<name>", methods=["POST"])
def api_runbook(name):
    return jsonify(register.generate_runbook(name)), 410


@app.route("/api/bootstrap/<name>", methods=["POST"])
def api_bootstrap(name):
    return _start(f"bootstrap:{name}", lambda: register.bootstrap_handoff(name))


@app.route("/api/consolidate/<name>", methods=["POST"])
def api_consolidate(name):
    return _start(f"consolidate:{name}", lambda: register.consolidate_handoffs(name))


@app.route("/api/context/<name>", methods=["GET", "POST"])
def api_context(name):
    if request.method == "POST":
        return _start(f"checkpoint:{name}", lambda: register.refresh_project(name))
    result = register.refresh_project(name)
    if result.get("status") == "error":
        return jsonify(result), 409
    p = register.project(name)
    if not p:
        return jsonify({"status": "error", "reason": "project not found"}), 404
    info = register.context_info(p["name"])
    if not info["has_context"]:
        return jsonify({"status": "error", "reason": "context not generated"}), 404
    headers = {}
    if request.args.get("download") == "1":
        headers["Content-Disposition"] = f'attachment; filename="{register.context_name(p["name"])}"'
    try:
        text = checkpoints.export_context(name, compact=request.args.get("compact") == "1")
    except ValueError as e:
        return jsonify({"status": "error", "reason": str(e)}), 409
    return Response(text, mimetype="text/plain", headers=headers)


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
    results = {p["name"]: register.refresh_project(p["name"]) for p in register.project_list()
               if not p["archived"] and p["handoff_count"]}
    return jsonify({"status": "ok", "projects": len(register.all_projects()), "checkpoints": results})


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
    """Provide a complete-replacement conversation handoff or legacy debrief."""
    fname = "debrief_prompt.md" if kind == "debrief" else "handoff_prompt.md"
    try:
        template = (_PROMPT_DIR / fname).read_text(encoding="utf-8")
    except OSError:
        return f"{fname} is missing from the container."

    if kind == "handoff":
        created_at = datetime.now(timezone.utc).isoformat(
            timespec="microseconds").replace("+00:00", "Z")
        template = template.replace("<CREATED_AT>", created_at)

    if kind == "debrief":
        p = register.project(project) if project else None
        name = p["name"] if p else (project or "<project slug>")
        repo = (p.get("repo") if p else "") or \
            "(no repo recorded — set one on the project page)"
        return template.replace("<PROJECT>", name).replace("<REPO>", repo)


    if project:
        p = register.project(project)
        if p:
            name = p["name"]
            repo = (
                p.get("repo")
                or "(no repo recorded — set one on the project page)"
            )
            checkpoint = register.handoff_prompt_context(name)
            try:
                parent = checkpoints.identity(name)
            except ValueError as e:
                try:
                    parent, conflicting_ids, material = checkpoints.resolution(name)
                    checkpoint = register.context_info(name).get("context", "(No accepted snapshot yet.)")
                    checkpoint += "\n\nEXPLICIT RECONCILIATION REQUIRED: compare every version below; never select one merely by timestamp.\n" + material
                    template = template.replace("<RECONCILES>", "reconciles: " + json.dumps(conflicting_ids))
                except ValueError as recovery_error:
                    return "Checkpoint import failed: " + str(e) + ". " + str(recovery_error)
            template = template.replace("<RECONCILES>", "")
            template = template.replace("<BASED_ON>", parent)
            selection_rule = (
                f"This prompt is already scoped to the exact Register project "
                f"`{name}`. Use exactly `{name}` in the `project:` field. "
                "Do not invent, abbreviate, rename, or change its capitalisation."
            )
            return (
                template
                .replace("<PROJECT>", name)
                .replace("<REPO>", repo)
                .replace("<PROJECT_SELECTION_RULE>", selection_rule)
                .replace("<CURRENT_CHECKPOINT>", checkpoint)
                .replace("<SLUG_LIST>", f"  {name}")
            )

    selection_rule = (
        "Choose the project value by copying one exact slug from the list at "
        "the end of this prompt, including its capitalisation. Do not invent "
        "a new slug, abbreviate one, or coin a variant. If none fits, use the "
        "literal value `NEW` and say so in one line at the very end."
    )
    return (
        template
        .replace("<PROJECT>", "<SLUG>")
        .replace("<REPO>", "(not project-scoped)")
        .replace("<PROJECT_SELECTION_RULE>", selection_rule)
        .replace(
            "<CURRENT_CHECKPOINT>",
            "(No project-specific checkpoint supplied. Use the full "
            "conversation and choose a project from the slug list below.)",
        )
        .replace("<SLUG_LIST>", _slug_list())
        .replace("<BASED_ON>", "ROOT")
        .replace("<RECONCILES>", "")
    )



@app.route("/prompt")
@app.route("/prompt/<kind>")
def prompt_page(kind: str = "handoff"):
    """Plain text so it can be curled, piped, or selected and copied.
    /prompt                         generic session handoff with current slugs
    /prompt?project=Name            project-specific handoff with prior CTX
    /prompt/debrief?project=Name    full project debrief, scoped to one
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
        "summary_backend": "conversation-checkpoint",
    })


# ── scheduled refresh ───────────────────────────────────────────────
# Routine scans only validate/publish synced conversation checkpoints. No AI.


def scheduled_refresh():
    register.invalidate()
    done = 0
    for p in register.project_list():
        if p["archived"] or not p["handoff_count"]:
            continue
        try:
            res = register.refresh_project(p["name"])
            logger.info("checkpoint import %s → %s %s", p["name"], res.get("status"), res.get("reason", ""))
            done += res.get("status") == "generated"
        except Exception:
            logger.exception("checkpoint import failed for %s", p["name"])
    logger.info("checkpoint scan complete: %d published; no AI calls", done)


def scheduled_synthesis():
    """Run the weekly whole-estate Gemini review in a child process."""
    script = Path(__file__).with_name("synthesise.py")
    cmd = [sys.executable, str(script), "--vault", str(register.VAULT_PATH)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception:
        logger.exception("weekly synthesis failed to start")
        return
    if proc.stdout.strip():
        logger.info("weekly synthesis stdout: %s", proc.stdout.strip())
    if proc.stderr.strip():
        logger.info("weekly synthesis stderr: %s", proc.stderr.strip())
    if proc.returncode:
        logger.error("weekly synthesis exited %d", proc.returncode)
    else:
        logger.info("weekly synthesis complete")


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
    logger.info("checkpoint scan scheduled (daily %02d:00; no AI)", _hour)

if _enabled("WEEKLY_SYNTHESIS", os.environ.get("MONTHLY_SYNTHESIS", "true")):
    _syn_hour = int(os.environ.get("WEEKLY_SYNTHESIS_HOUR", "4"))
    _syn_day = os.environ.get("WEEKLY_SYNTHESIS_DAY", "sun")
    _sched.add_job(scheduled_synthesis, "cron", day_of_week=_syn_day, hour=_syn_hour, minute=0,
                   id="weekly_synthesis", coalesce=True, max_instances=1)
    _sched_jobs += 1
    logger.info("weekly synthesis scheduled (%s at %02d:00)", _syn_day, _syn_hour)

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

logger.info("register ready: vault=%s checkpoints=conversation-authored; routine AI calls=0",
            register.VAULT_PATH)
