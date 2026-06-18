#!/usr/bin/env python3
"""
Веб-интерфейс для osnovateli_doc_framework.
Запуск: python web/app.py
"""
import importlib
import hashlib
import atexit
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(os.getenv("BASE_DIR", str(DEFAULT_BASE_DIR))).resolve()
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from photo_placeholder_ops import (
    build_placeholder_render_cmd,
    find_source_image,
    is_realesrgan_installed,
)
from path_utils import list_projects as scan_projects, ensure_project_marker, is_project_dir, read_project_marker

try:
    from flask import Flask, jsonify, render_template, request, Response, stream_with_context, send_file, abort
except ImportError:
    print("Flask не установлен. Установите: pip install flask")
    sys.exit(1)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

# ── Global state ───────────────────────────────────────────────────────────────
_job_lock = threading.Lock()
_job_condition = threading.Condition(threading.RLock())
_current_job: dict = {
    "running": False,
    "proc": None,
    "events": [],
    "event_seq": 0,
    "log_history": [],
    "job_title": "",
    "steps": [],
    "step_index": 0,
    "step_title": "",
    "phase": "idle",
    "progress_percent": 0.0,
    "started_at": None,
    "finished_at": None,
    "step_started_at": None,
    "eta_seconds": None,
    "step_eta_seconds": None,
    "sub_index": None,
    "sub_total": None,
}
_settings: dict = {
    "base_dir": str(BASE_DIR),
    "projects_root": str(BASE_DIR / "data"),
    "cookies_file": str((BASE_DIR / "cookies.txt").resolve()) if (BASE_DIR / "cookies.txt").exists() else "",
}
_gazety_watch_lock = threading.Lock()
_gazety_watch: dict = {"folder": None, "files": {}}
_gazety_render_lock = threading.Lock()
_gazety_render_processes: dict[str, subprocess.Popen] = {}
_gazety_cancelled_renders: set[str] = set()


def _data_dir() -> Path:
    return Path(_settings.get("projects_root") or (Path(_settings["base_dir"]) / "data")).expanduser().resolve()


def _project_dir(project_name: str) -> Path:
    return _data_dir() / project_name


def _list_projects() -> list[dict]:
    return scan_projects(_data_dir())



def _ensure_project(project_name: str, projects_root: Path | None = None) -> dict:
    root = (projects_root or _data_dir()).expanduser().resolve()
    project_dir = root / project_name
    return ensure_project_marker(
        project_dir,
        project_name=project_name,
        base_dir=Path(_settings["base_dir"]).expanduser().resolve(),
        projects_root=root,
    )


def _choose_folder_dialog(initial_path: Path | None = None, prompt: str = "Выберите папку") -> str | None:
    initial_path = (initial_path or _data_dir()).expanduser().resolve()
    if sys.platform == "darwin":
        script = (
            'set chosenFolder to choose folder with prompt "{}" default location POSIX file "{}"\n'
            'return POSIX path of chosenFolder'
        ).format(prompt.replace('"', '\\"'), str(initial_path).replace('"', '\\"'))
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if res.returncode != 0:
            return None
        return (res.stdout or "").strip() or None
    return None


def _choose_file_dialog(initial_path: Path | None = None, prompt: str = "Выберите файл", file_type: str = "") -> str | None:
    initial_path = (initial_path or BASE_DIR).expanduser().resolve()
    if sys.platform == "darwin":
        type_clause = f' of type {json.dumps([file_type])}' if file_type else ""
        script = (
            'set chosenFile to choose file with prompt "{}" default location POSIX file "{}"{}\n'
            'return POSIX path of chosenFile'
        ).format(
            prompt.replace('"', '\\"'),
            str(initial_path).replace('"', '\\"'),
            type_clause,
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if res.returncode != 0:
            return None
        return (res.stdout or "").strip() or None
    return None


def _ensure_mask_preview_video(base_dir: Path) -> Path:
    alpha_mp4 = base_dir / "assets" / "alpha_mask.mp4"
    preview_mp4 = base_dir / "assets" / "_mask_preview_anim_v1.mp4"
    if preview_mp4.exists():
        return preview_mp4
    if not alpha_mp4.exists():
        raise FileNotFoundError(alpha_mp4)
    preview_cmd = [
        "ffmpeg", "-y", "-i", str(alpha_mp4),
        "-vf", "format=gray,lut=y='if(gte(val\\,128)\\,255\\,0)'",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(preview_mp4)
    ]
    res = subprocess.run(preview_cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", "ignore") or "mask preview generation failed")
    return preview_mp4


# ── Script tasks (mirrors SCRIPT_TASKS in main.py) ────────────────────────────
SCRIPT_TASKS = [
    {"id": "smart_cropping",      "title": "Кроп / Nano Banana 2",                    "script": "2.1_smart_cropping.py",      "needs_project": True,  "needs_image_mode": True},
    {"id": "pullvids_download",   "title": "Скачать YouTube видео (yt-dlp)",          "script": "3.4_pullvids_download.py",   "needs_project": True},
    {"id": "pulltube_rename",     "title": "Переименовать YouTube видео",              "script": "4_pulltube_rename.py",       "needs_project": True,  "project_arg": True},
    {"id": "motionarray_rename",  "title": "Переименовать MotionArray видео",          "script": "4.1_motionarray_rename.py",  "needs_project": True,  "project_arg": True},
    {"id": "photo_placeholders",  "title": "Создать video placeholders из фото",       "script": "5_photo_placeholders.py",    "needs_project": True},
    {"id": "screenshots",         "title": "Скриншоты other links",                    "script": "7_screenshot_other_links.py","needs_project": True,  "project_arg": True},
    {"id": "sort_errors",         "title": "Разобрать ошибки скачивания",              "script": "sort_errors.py",             "needs_project": False},
]

CORE_STAGES = [
    {"id": "stage_structure",   "title": "Создать структуру папок",         "run_mode": "stage_structure",   "needs_project": True},
    {"id": "stage_parse_links", "title": "Парсинг Google таблицы",          "run_mode": "stage_parse_links", "needs_project": True,  "needs_sheets": True},
    {"id": "stage_xml",         "title": "XML плейсхолдеры",                "run_mode": "stage_xml",         "needs_project": True},
    {"id": "stage_enrich",      "title": "Обогащение YouTube-каналов",      "run_mode": "stage_enrich",      "needs_project": True},
    {"id": "stage_author",      "title": "Создать PNG-плашки источников",   "run_mode": "stage_author",      "needs_project": True},
    {"id": "stage_images",      "title": "Скачать изображения",             "run_mode": "stage_images",      "needs_project": True},
]

FLOW_STEP_CATALOG = [
    {"id": "stage_structure", "kind": "stage", "title": "Создать структуру папок"},
    {"id": "stage_parse_links", "kind": "stage", "title": "Парсинг Google таблицы", "needs_sheets": True},
    {"id": "stage_xml", "kind": "stage", "title": "XML плейсхолдеры"},
    {"id": "stage_enrich", "kind": "stage", "title": "Обогащение YouTube-каналов"},
    {"id": "stage_author", "kind": "stage", "title": "Создать PNG-плашки источников"},
    {"id": "stage_images", "kind": "stage", "title": "Скачать изображения"},
    {"id": "pullvids_download", "kind": "script", "title": "Скачать YouTube видео (yt-dlp)"},
    {"id": "pulltube_rename", "kind": "script", "title": "Переименовать YouTube видео"},
    {"id": "motionarray_rename", "kind": "script", "title": "Переименовать MotionArray видео"},
    {"id": "smart_cropping", "kind": "script", "title": "Кроп / Nano Banana 2"},
    {"id": "photo_placeholders", "kind": "script", "title": "Создать video placeholders из фото"},
    {"id": "screenshots", "kind": "script", "title": "Скриншоты other links"},
]

DEFAULT_NEW_PROJECT_STEP_IDS = [step["id"] for step in FLOW_STEP_CATALOG]
DEFAULT_EDITS_STEP_IDS = [step["id"] for step in FLOW_STEP_CATALOG if step["id"] != "stage_structure"]
_FLOW_STEP_TITLES = {step["id"]: step["title"] for step in FLOW_STEP_CATALOG}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean_log_text(text: str) -> str:
    return _ANSI_RE.sub("", str(text or "")).strip()


def _duration_from_eta(value: str | None) -> int | None:
    if not value:
        return None
    parts = [int(part) for part in value.split(":") if part.isdigit()]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _job_status_locked() -> dict:
    started_at = _current_job.get("started_at")
    step_started_at = _current_job.get("step_started_at")
    now = time.time()
    steps = _current_job.get("steps") or []
    return {
        "running": bool(_current_job.get("running")),
        "job_title": _current_job.get("job_title") or "",
        "steps": steps,
        "step_index": int(_current_job.get("step_index") or 0),
        "total_steps": len(steps),
        "step_title": _current_job.get("step_title") or "",
        "phase": _current_job.get("phase") or "idle",
        "progress_percent": round(float(_current_job.get("progress_percent") or 0), 1),
        "eta_seconds": _current_job.get("eta_seconds"),
        "step_eta_seconds": _current_job.get("step_eta_seconds"),
        "elapsed_seconds": int(now - started_at) if started_at else 0,
        "step_elapsed_seconds": int(now - step_started_at) if step_started_at else 0,
        "last_event_seq": int(_current_job.get("event_seq") or 0),
        "log_history": list(_current_job.get("log_history") or []),
    }


def _estimate_eta_locked(progress_percent: float) -> int | None:
    if progress_percent <= 1 or progress_percent >= 100:
        return None
    started_at = _current_job.get("started_at")
    if not started_at:
        return None
    elapsed = max(1.0, time.time() - started_at)
    return int(elapsed * (100.0 - progress_percent) / progress_percent)


def _set_progress_locked(step_progress: float | None = None, absolute_progress: float | None = None, eta_seconds: int | None = None) -> None:
    steps = _current_job.get("steps") or []
    total_steps = max(1, len(steps))
    step_index = max(1, int(_current_job.get("step_index") or 1))

    if step_progress is not None:
        step_progress = max(0.0, min(100.0, float(step_progress)))
        absolute_progress = ((step_index - 1) + step_progress / 100.0) / total_steps * 100.0
        step_started_at = _current_job.get("step_started_at")
        if eta_seconds is None and step_started_at and 1 < step_progress < 100:
            elapsed = max(1.0, time.time() - step_started_at)
            eta_seconds = int(elapsed * (100.0 - step_progress) / step_progress)

    if absolute_progress is not None:
        _current_job["progress_percent"] = max(0.0, min(100.0, float(absolute_progress)))

    _current_job["step_eta_seconds"] = eta_seconds
    _current_job["eta_seconds"] = eta_seconds if eta_seconds is not None else _estimate_eta_locked(_current_job["progress_percent"])


def _set_step_locked(title: str) -> None:
    clean_title = _clean_log_text(title)
    if not clean_title:
        return
    steps = _current_job.get("steps") or []
    try:
        index = steps.index(clean_title) + 1
    except ValueError:
        if not steps:
            steps = [clean_title]
            _current_job["steps"] = steps
        index = min(len(steps), max(1, int(_current_job.get("step_index") or 1)))
    if _current_job.get("step_title") != clean_title:
        _current_job["step_started_at"] = time.time()
        _current_job["sub_index"] = None
        _current_job["sub_total"] = None
        _current_job["step_eta_seconds"] = None
    _current_job["step_title"] = clean_title
    _current_job["step_index"] = index
    _current_job["phase"] = "running"
    _set_progress_locked(step_progress=0.0)


def _parse_job_line_locked(text: str) -> None:
    clean = _clean_log_text(text)
    if not clean:
        return

    if "Получаю информацию о каналах" in clean:
        _set_step_locked("Метаданные каналов")
        return
    if re.search(r"===\s*Скачивание\s*===", clean):
        _set_step_locked("Скачивание видео")
        return

    step_match = re.search(r"===\s*Шаг(?:\s+\d+/\d+)?:\s*(.+?)\s*===", clean)
    if step_match:
        _set_step_locked(step_match.group(1))
        return

    numbered_step = re.search(r"===\s*Шаг\s+(\d+)/(\d+):\s*(.+?)\s*===", clean)
    if numbered_step:
        _current_job["steps"] = _current_job.get("steps") or [f"Шаг {i}" for i in range(1, int(numbered_step.group(2)) + 1)]
        _current_job["step_index"] = int(numbered_step.group(1))
        _set_step_locked(numbered_step.group(3))
        return

    item_match = re.search(r"\[(\d+)/(\d+)\]", clean)
    if item_match:
        sub_index = int(item_match.group(1))
        sub_total = max(1, int(item_match.group(2)))
        _current_job["sub_index"] = sub_index
        _current_job["sub_total"] = sub_total
        _set_progress_locked(step_progress=sub_index / sub_total * 100.0)

    download_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%\s+.*?(?:ETA\s+([0-9:]+))?", clean, re.I)
    if download_match:
        download_progress = float(download_match.group(1))
        eta_seconds = _duration_from_eta(download_match.group(2))
        sub_index = _current_job.get("sub_index")
        sub_total = _current_job.get("sub_total")
        if sub_index and sub_total:
            step_progress = ((int(sub_index) - 1) + download_progress / 100.0) / max(1, int(sub_total)) * 100.0
        else:
            step_progress = download_progress
        _set_progress_locked(step_progress=step_progress, eta_seconds=eta_seconds)


def _emit_job_event(item: dict) -> dict:
    with _job_condition:
        event = dict(item)
        _current_job["event_seq"] = int(_current_job.get("event_seq") or 0) + 1
        event["seq"] = _current_job["event_seq"]
        if event.get("type") in {"start", "log", "error", "done"}:
            if event.get("type") == "start":
                _current_job["phase"] = "running"
            elif event.get("type") == "log":
                _parse_job_line_locked(event.get("text") or "")
            elif event.get("type") == "error":
                _current_job["phase"] = "error"
            elif event.get("type") == "done":
                _current_job["phase"] = "done" if event.get("code") == 0 else "failed"
                _current_job["progress_percent"] = 100.0 if event.get("code") == 0 else _current_job.get("progress_percent", 0.0)
                _current_job["eta_seconds"] = None
                _current_job["step_eta_seconds"] = None
                _current_job["finished_at"] = time.time()
            _current_job.setdefault("log_history", []).append(event)
            if len(_current_job["log_history"]) > 2000:
                _current_job["log_history"] = _current_job["log_history"][-2000:]
        _current_job.setdefault("events", []).append(event)
        if len(_current_job["events"]) > 2500:
            _current_job["events"] = _current_job["events"][-2500:]
        status_event = {"type": "status", "status": _job_status_locked()}
        _current_job["event_seq"] += 1
        status_event["seq"] = _current_job["event_seq"]
        _current_job["events"].append(status_event)
        _job_condition.notify_all()
        return event


# ── Dependency checks ──────────────────────────────────────────────────────────
_PYTHON_DEPS = {
    "requests": "requests",
    "gspread": "gspread",
    "python-dotenv": "dotenv",
    "google-auth": "google.oauth2",
    "Pillow": "PIL",
    "playwright": "playwright",
    "questionary": "questionary",
    "flask": "flask",
    "rumps": "rumps",
}


def check_deps() -> dict:
    result: dict = {}
    for pip_name, import_name in _PYTHON_DEPS.items():
        try:
            importlib.import_module(import_name)
            result[pip_name] = {"ok": True, "type": "python"}
        except ImportError:
            result[pip_name] = {"ok": False, "type": "python"}

    result["ffmpeg"] = {"ok": shutil.which("ffmpeg") is not None, "type": "system"}
    result["yt-dlp"] = {"ok": shutil.which("yt-dlp") is not None, "type": "system"}
    result["Real-ESRGAN"] = {"ok": is_realesrgan_installed(Path(_settings["base_dir"])), "type": "tool"}
    return result


# ── Job runner ─────────────────────────────────────────────────────────────────
def _run_job(cmd, env=None, cwd=None):
    _emit_job_event({"type": "start", "cmd": " ".join(str(c) for c in cmd)})
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(cwd or BASE_DIR),
            bufsize=1,
            start_new_session=True,
        )
        with _job_condition:
            _current_job["proc"] = proc
            _job_condition.notify_all()
        for line in proc.stdout:
            _emit_job_event({"type": "log", "text": line.rstrip()})
        proc.wait()
        code = proc.returncode
        _emit_job_event({"type": "done", "code": code, "cancelled": code == -signal.SIGTERM})
    except Exception as exc:
        _emit_job_event({"type": "error", "text": str(exc)})
        _emit_job_event({"type": "done", "code": 1})
    finally:
        with _job_condition:
            _current_job["running"] = False
            _current_job["proc"] = None
            _job_condition.notify_all()


def _start_job(cmd, env=None, cwd=None, job_title: str = "", steps: list[str] | None = None):
    with _job_lock:
        with _job_condition:
            if _current_job["running"]:
                return False, "Уже выполняется другая задача"
            clean_steps = [str(step).strip() for step in (steps or []) if str(step).strip()]
            _current_job.update({
                "running": True,
                "proc": None,
                "events": [],
                "event_seq": 0,
                "log_history": [],
                "job_title": job_title or "Задача",
                "steps": clean_steps,
                "step_index": 1 if clean_steps else 0,
                "step_title": clean_steps[0] if clean_steps else (job_title or "Задача"),
                "phase": "starting",
                "progress_percent": 0.0,
                "started_at": time.time(),
                "finished_at": None,
                "step_started_at": time.time(),
                "eta_seconds": None,
                "step_eta_seconds": None,
                "sub_index": None,
                "sub_total": None,
            })
            _job_condition.notify_all()
    threading.Thread(
        target=_run_job, args=(cmd,), kwargs={"env": env, "cwd": cwd}, daemon=True
    ).start()
    return True, "ok"


def _build_env(**kwargs) -> dict:
    env = os.environ.copy()
    env["BASE_DIR"] = _settings["base_dir"]
    env["PROJECTS_ROOT"] = str(_data_dir())
    if _settings.get("cookies_file"):
        env["COOKIES_FILE"] = str(_settings["cookies_file"])
    env["PYTHONUNBUFFERED"] = "1"
    bd = Path(_settings["base_dir"])
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(bd / "scripts"), str(bd / "core"), env.get("PYTHONPATH", "")])
    )
    for k, v in kwargs.items():
        if v is not None:
            env[k.upper()] = str(v)
    return env


def _main_py() -> Path:
    return Path(_settings["base_dir"]) / "core" / "main.py"


def _normalize_flow_steps(flow_name: str, selected_steps) -> list[str]:
    if flow_name == "new_project":
        allowed = DEFAULT_NEW_PROJECT_STEP_IDS
    elif flow_name == "edits":
        allowed = DEFAULT_EDITS_STEP_IDS
    else:
        raise ValueError(f"unknown flow: {flow_name}")

    requested = {str(step).strip() for step in (selected_steps or []) if str(step).strip()}
    if not requested:
        return list(allowed)
    return [step_id for step_id in allowed if step_id in requested]


def _service_email() -> str:
    email = os.environ.get("CLIENT_EMAIL", "")
    if email:
        return email
    env_file = Path(_settings["base_dir"]) / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("CLIENT_EMAIL="):
                return line.split("=", 1)[1].strip()
    return ""


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template(
        "index.html",
        settings=_settings,
        projects=_list_projects(),
        deps=check_deps(),
        core_stages=CORE_STAGES,
        script_tasks=SCRIPT_TASKS,
        flow_steps=FLOW_STEP_CATALOG,
        default_new_project_steps=DEFAULT_NEW_PROJECT_STEP_IDS,
        default_edits_steps=DEFAULT_EDITS_STEP_IDS,
        service_email=_service_email(),
    )


@app.route("/api/deps")
def api_deps():
    return jsonify(check_deps())


@app.route("/api/projects")
def api_projects():
    return jsonify(_list_projects())


@app.route("/api/scripts")
def api_scripts():
    return jsonify({"core_stages": CORE_STAGES, "script_tasks": SCRIPT_TASKS})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        if "base_dir" in data:
            p = Path(str(data["base_dir"])).expanduser().resolve()
            if not p.exists():
                return jsonify({"error": f"Папка не найдена: {p}"}), 400
            _settings["base_dir"] = str(p)
        if "projects_root" in data:
            p = Path(str(data["projects_root"])).expanduser().resolve()
            if not p.exists():
                return jsonify({"error": f"Папка не найдена: {p}"}), 400
            _settings["projects_root"] = str(p)
        if "cookies_file" in data:
            cookies_file = str(data["cookies_file"] or "").strip()
            if cookies_file:
                p = Path(cookies_file).expanduser().resolve()
                if not p.exists() or not p.is_file():
                    return jsonify({"error": f"Файл не найден: {p}"}), 400
                _settings["cookies_file"] = str(p)
            else:
                _settings["cookies_file"] = ""
        return jsonify(_settings)
    return jsonify(_settings)


@app.route("/api/choose_folder", methods=["POST"])
def api_choose_folder():
    data = request.get_json() or {}
    current_path = Path((data.get("current_path") or str(_data_dir()))).expanduser()
    prompt = (data.get("prompt") or "Выберите папку").strip()
    chosen = _choose_folder_dialog(current_path, prompt)
    if not chosen:
        return jsonify({"error": "Папка не выбрана"}), 400
    return jsonify({"path": chosen})


@app.route("/api/choose_file", methods=["POST"])
def api_choose_file():
    data = request.get_json() or {}
    current_path = Path((data.get("current_path") or _settings.get("cookies_file") or _settings["base_dir"])).expanduser()
    prompt = (data.get("prompt") or "Выберите файл").strip()
    file_type = (data.get("file_type") or "").strip()
    chosen = _choose_file_dialog(current_path, prompt, file_type)
    if not chosen:
        return jsonify({"error": "Файл не выбран"}), 400
    return jsonify({"path": chosen})


@app.route("/api/projects/create", methods=["POST"])
def api_create_project():
    data = request.get_json() or {}
    project_name = (data.get("project_name") or "").strip()
    projects_root = Path((data.get("projects_root") or str(_data_dir()))).expanduser().resolve()
    if not project_name:
        return jsonify({"error": "Укажите название проекта"}), 400
    projects_root.mkdir(parents=True, exist_ok=True)
    marker = _ensure_project(project_name, projects_root)
    _settings["projects_root"] = str(projects_root)
    return jsonify({"project": marker, "projects": _list_projects()})


@app.route("/api/projects/import", methods=["POST"])
def api_import_project():
    data = request.get_json() or {}
    project_path_raw = (data.get("project_path") or "").strip()
    if not project_path_raw:
        return jsonify({"error": "Укажите путь к проекту"}), 400
    project_dir = Path(project_path_raw).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return jsonify({"error": f"Папка проекта не найдена: {project_dir}"}), 400
    if not is_project_dir(project_dir):
        return jsonify({"error": "В выбранной папке не найден проект Osnovateli"}), 400
    _settings["projects_root"] = str(project_dir.parent)
    marker = ensure_project_marker(
        project_dir,
        project_name=project_dir.name,
        base_dir=Path(_settings["base_dir"]).expanduser().resolve(),
        projects_root=project_dir.parent,
    )
    return jsonify({"project": marker, "projects": _list_projects()})


@app.route("/api/projects/open_folder", methods=["POST"])
def api_open_project_folder():
    data = request.get_json() or {}
    project_name = (data.get("project_name") or "").strip()
    if not project_name:
        return jsonify({"error": "Укажите проект"}), 400
    project_dir = _project_dir(project_name)
    if not project_dir.exists():
        return jsonify({"error": f"Папка проекта не найдена: {project_dir}"}), 404
    if sys.platform == "darwin":
        subprocess.run(["open", str(project_dir)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", str(project_dir)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(project_dir))  # type: ignore[attr-defined]
    return jsonify({"status": "ok"})


@app.route("/api/projects/state")
def api_project_state():
    project_name = (request.args.get("project_name") or "").strip()
    if not project_name:
        return jsonify({"error": "project_name required"}), 400
    project_dir = _project_dir(project_name)
    if not project_dir.exists():
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify(read_project_marker(project_dir))


@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    proc = _current_job.get("proc")
    if not _current_job["running"] or proc is None:
        return jsonify({"error": "Нет активной задачи"}), 400
    try:
        import time
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(1)
        try:
            if proc.poll() is None:
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _emit_job_event({"type": "log", "text": "⛔ Задача отменена пользователем"})
        return jsonify({"status": "cancelled"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Pause / Resume ────────────────────────────────────────────────────────────
@app.route("/api/pause", methods=["POST"])
def api_pause():
    if not _current_job["running"]:
        return jsonify({"error": "Нет активной задачи"}), 400
    flag = Path(_settings["base_dir"]) / ".pause_requested"
    flag.touch()
    _emit_job_event({"type": "log", "text": "⏸️  Запрос паузы — ожидаю завершения текущего шага..."})
    return jsonify({"status": "pause_requested"})


@app.route("/api/run/resume", methods=["POST"])
def api_run_resume():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    state = read_project_marker(_project_dir(pname))
    if state.get("status") != "paused":
        return jsonify({"error": "Проект не на паузе"}), 400
    pending_steps = state.get("pending_steps") or []
    if not pending_steps:
        return jsonify({"error": "Нет шагов для продолжения — пайплайн завершён"}), 400
    flow_name = state.get("paused_flow") or "new_project"
    image_mode = state.get("paused_image_mode") or "crop"
    paused_wave = state.get("paused_wave") or ""
    env = _build_env(project_name=pname, image_processing_mode=image_mode)
    env["FLOW_SELECTION_JSON"] = json.dumps(pending_steps, ensure_ascii=False)
    if paused_wave:
        env["UPD_SUBDIR"] = paused_wave
    steps = [_FLOW_STEP_TITLES.get(step_id, step_id) for step_id in pending_steps]
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", flow_name], env=env,
                         job_title=f"Продолжение: {pname}", steps=steps)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


# ── Install routes ─────────────────────────────────────────────────────────────
@app.route("/api/run/install_deps", methods=["POST"])
def api_install_deps():
    req_file = Path(_settings["base_dir"]) / "requirements.txt"
    if not req_file.exists():
        return jsonify({"error": "requirements.txt не найден"}), 400
    ok, msg = _start_job([sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                         job_title="Установка Python-зависимостей", steps=["pip install"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_playwright", methods=["POST"])
def api_install_playwright():
    ok, msg = _start_job([sys.executable, "-m", "playwright", "install", "chromium"],
                         job_title="Установка Playwright Chromium", steps=["playwright install chromium"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_ffmpeg", methods=["POST"])
def api_install_ffmpeg():
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "install_ffmpeg"],
                         job_title="Установка ffmpeg", steps=["Проверка и установка ffmpeg"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_realesrgan", methods=["POST"])
def api_install_realesrgan():
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "install_realesrgan"],
                         job_title="Установка Real-ESRGAN", steps=["Проверка и установка Real-ESRGAN"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_all", methods=["POST"])
def api_install_all():
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "install"],
                         job_title="Установка всех зависимостей",
                         steps=["Python-пакеты", "Playwright Chromium", "ffmpeg", "Real-ESRGAN", "Docker Desktop"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


# ── Pipeline routes ────────────────────────────────────────────────────────────
@app.route("/api/run/new_project", methods=["POST"])
def api_run_new_project():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    sheets_url = (data.get("sheets_url") or "").strip()
    image_mode = data.get("image_mode", "crop")
    video_quality = (data.get("video_quality") or "original").strip().lower()
    projects_root_raw = (data.get("projects_root") or str(_data_dir())).strip()
    selected_steps = _normalize_flow_steps("new_project", data.get("selected_steps") or [])
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not selected_steps:
        return jsonify({"error": "Выберите хотя бы один шаг"}), 400
    if "stage_parse_links" in selected_steps and not sheets_url:
        return jsonify({"error": "Укажите ссылку на Google таблицу"}), 400
    projects_root = Path(projects_root_raw).expanduser().resolve()
    projects_root.mkdir(parents=True, exist_ok=True)
    _settings["projects_root"] = str(projects_root)
    _ensure_project(pname, projects_root)
    env = _build_env(project_name=pname, image_processing_mode=image_mode,
                     spreadsheet_url=sheets_url, video_quality=video_quality)
    env["FLOW_SELECTION_JSON"] = json.dumps(selected_steps, ensure_ascii=False)
    steps = [_FLOW_STEP_TITLES.get(step_id, step_id) for step_id in selected_steps]
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "new_project"], env=env,
                         job_title=f"Новый проект: {pname}", steps=steps)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/edits", methods=["POST"])
def api_run_edits():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    sheets_url = (data.get("sheets_url") or "").strip()
    image_mode = data.get("image_mode", "crop")
    video_quality = (data.get("video_quality") or "original").strip().lower()
    selected_steps = _normalize_flow_steps("edits", data.get("selected_steps") or [])
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not selected_steps:
        return jsonify({"error": "Выберите хотя бы один шаг"}), 400
    if "stage_parse_links" in selected_steps and not sheets_url:
        return jsonify({"error": "Укажите ссылку на Google таблицу"}), 400
    env = _build_env(project_name=pname, image_processing_mode=image_mode,
                     spreadsheet_url=sheets_url, video_quality=video_quality)
    env["FLOW_SELECTION_JSON"] = json.dumps(selected_steps, ensure_ascii=False)
    steps = [_FLOW_STEP_TITLES.get(step_id, step_id) for step_id in selected_steps]
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "edits"], env=env,
                         job_title=f"Правки: {pname}", steps=steps)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/direct_video", methods=["POST"])
def api_run_direct_video():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    video_quality = (data.get("video_quality") or "original").strip().lower()
    raw_urls = data.get("urls") or []
    urls = [u.strip() for u in raw_urls if str(u).strip().startswith("http")]
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not urls:
        return jsonify({"error": "Укажите хотя бы одну ссылку"}), 400
    env = _build_env(project_name=pname, video_quality=video_quality)
    env["VIDEO_URLS"] = "\n".join(urls)
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "direct_video"], env=env,
                         job_title=f"Скачивание видео: {pname}", steps=["Метаданные каналов", "Скачивание видео", "Плашки источников"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/stage", methods=["POST"])
def api_run_stage():
    data = request.get_json() or {}
    run_mode = (data.get("run_mode") or "").strip()
    pname = (data.get("project_name") or "").strip()
    sheets_url = (data.get("sheets_url") or "").strip()
    image_mode = data.get("image_mode", "crop")

    stage = next((s for s in CORE_STAGES if s["run_mode"] == run_mode), None)
    if not stage:
        return jsonify({"error": f"Неизвестная стадия: {run_mode}"}), 400
    if stage.get("needs_project") and not pname:
        return jsonify({"error": "Укажите проект"}), 400
    if stage.get("needs_sheets") and not sheets_url:
        return jsonify({"error": "Укажите ссылку на Google таблицу"}), 400

    env = _build_env(project_name=pname, image_processing_mode=image_mode,
                     spreadsheet_url=sheets_url if sheets_url else None)
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", run_mode], env=env,
                         job_title=stage["title"], steps=[stage["title"]])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/script", methods=["POST"])
def api_run_script():
    data = request.get_json() or {}
    script_id = (data.get("script_id") or "").strip()
    pname = (data.get("project_name") or "").strip()
    image_mode = data.get("image_mode", "crop")

    task = next((t for t in SCRIPT_TASKS if t["id"] == script_id), None)
    if not task:
        return jsonify({"error": f"Скрипт не найден: {script_id}"}), 400
    if task.get("needs_project") and not pname:
        return jsonify({"error": "Укажите проект"}), 400

    env = _build_env(project_name=pname, image_processing_mode=image_mode)
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", f"script:{task['script']}"], env=env,
                         job_title=task["title"], steps=[task["title"]])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


# ── Photo placeholders editor ─────────────────────────────────────────────────
@app.route("/api/placeholders")
def api_placeholders():
    project = request.args.get("project", "").strip()
    subdir  = request.args.get("subdir",  "").strip()
    if not project:
        return jsonify({"error": "project required"}), 400
    ph_dir  = _data_dir() / project / "placeholders_photo"
    src_dir = _data_dir() / project / "images_cropped"
    if subdir:
        ph_dir  = ph_dir  / subdir
        src_dir = src_dir / subdir
    if not ph_dir.exists():
        return jsonify({"files": [], "project": project, "subdir": subdir})
    files = []
    for mov in sorted(ph_dir.glob("*.mov"), key=lambda p: p.stem):
        stem    = mov.stem
        has_src = any((src_dir / f"{stem}{e}").exists() for e in (".jpg", ".jpeg", ".png"))
        files.append({"name": stem, "has_src": has_src})
    return jsonify({"files": files, "project": project, "subdir": subdir})


@app.route("/api/placeholder_src")
def api_placeholder_src():
    project = request.args.get("project", "").strip()
    subdir  = request.args.get("subdir",  "").strip()
    name    = request.args.get("name",    "").strip()
    if not project or not name:
        abort(400)
    src_dir = _data_dir() / project / "images_cropped"
    if subdir:
        src_dir = src_dir / subdir
    p = find_source_image(src_dir, name)
    if p:
        return send_file(str(p))
    abort(404)


@app.route("/api/placeholder_encode", methods=["POST"])
def api_placeholder_encode():
    d       = request.get_json(silent=True) or {}
    project = d.get("project", "").strip()
    subdir  = d.get("subdir",  "").strip()
    name    = d.get("name",    "").strip()
    zoom    = min(3.0, max(0.25, float(d.get("zoom", 1.0))))
    x_off   = int(d.get("x", 0))
    y_off   = int(d.get("y", 0))
    if not project or not name:
        return jsonify({"error": "project and name required"}), 400
    src_dir = _data_dir() / project / "images_cropped"
    ph_dir  = _data_dir() / project / "placeholders_photo"
    if subdir:
        src_dir = src_dir / subdir
        ph_dir  = ph_dir  / subdir
    jpg = find_source_image(src_dir, name)
    if not jpg:
        return jsonify({"error": f"Source image not found: {name}"}), 404
    out       = ph_dir  / f"{name}.mov"
    ph_dir.mkdir(parents=True, exist_ok=True)
    try:
        cmd = build_placeholder_render_cmd(jpg, out, Path(_settings["base_dir"]), zoom=zoom, x_off=x_off, y_off=y_off)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500
    env = _build_env(project_name=project)
    ok, msg = _start_job(cmd, env=env, job_title=f"Рендер фото: {name}", steps=[f"Рендер {name}"])
    return (jsonify({"ok": True, "file": name}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/placeholder_upscale", methods=["POST"])
def api_placeholder_upscale():
    data = request.get_json(silent=True) or {}
    project = (data.get("project") or "").strip()
    subdir = (data.get("subdir") or "").strip()
    names = [str(name).strip() for name in (data.get("names") or []) if str(name).strip()]
    scale = int(data.get("scale") or 2)

    if not project:
        return jsonify({"error": "project required"}), 400
    if not names:
        return jsonify({"error": "Выберите хотя бы одно фото"}), 400
    if scale not in (2, 4):
        return jsonify({"error": "Поддерживается только 2x или 4x"}), 400

    script_path = Path(_settings["base_dir"]) / "scripts" / "6_upscale_photos.py"
    if not script_path.exists():
        return jsonify({"error": f"Скрипт не найден: {script_path.name}"}), 500

    env = _build_env(project_name=project, upd_subdir=subdir or None)
    env["UPSCALE_NAMES_JSON"] = json.dumps(names, ensure_ascii=False)
    env["UPSCALE_SCALE"] = str(scale)
    ok, msg = _start_job([sys.executable, str(_main_py()), "--run", "upscale_placeholders"], env=env,
                         job_title=f"Апскейл фото: {project}", steps=[f"Апскейл выбранных ({len(names)})"])
    return (jsonify({"ok": True, "count": len(names)}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/mask_preview")
def api_mask_preview():
    bd    = Path(_settings["base_dir"])
    try:
        cache = _ensure_mask_preview_video(bd)
    except FileNotFoundError:
        abort(404)
    except Exception:
        abort(500)
    return send_file(str(cache), mimetype="video/mp4")


# ── Газеты (newspaper animation) editor ───────────────────────────────────────
_GAZETY_ENV_VAR = "GAZETY_DIR"
_GAZETY_SLOTS = {"img_0": "img_0.jpg", "img_1": "img_1.jpg", "img_2": "img_2.png"}
_GAZETY_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}


def _gazety_dir() -> Path:
    configured = (os.getenv(_GAZETY_ENV_VAR) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(_settings["base_dir"]) / "assets_media" / "Paper").resolve()


def _gazety_scan_watch_folder():
    with _gazety_watch_lock:
        folder = _gazety_watch["folder"]
    if not folder or not folder.is_dir():
        return []

    found = {}
    for path in sorted(folder.rglob("*"), key=lambda p: str(p).lower()):
        if not path.is_file() or path.suffix.lower() not in _GAZETY_IMAGE_EXTS:
            continue
        try:
            stat = path.stat()
            relative = path.relative_to(folder)
        except (OSError, ValueError):
            continue
        identity = f"{relative}|{stat.st_mtime_ns}|{stat.st_size}"
        file_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        found[file_id] = path

    with _gazety_watch_lock:
        _gazety_watch["files"] = found

    return [
        {
            "id": file_id,
            "name": path.name,
            "relative_path": str(path.relative_to(folder)),
            "size": path.stat().st_size,
            "url": f"/api/gazety/watch/file/{file_id}",
        }
        for file_id, path in found.items()
    ]


@app.route("/api/gazety/watch/select", methods=["POST"])
def api_gazety_watch_select():
    if sys.platform != "darwin":
        return jsonify({"error": "Выбор папки поддерживается только на macOS"}), 400
    result = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Выберите папку с фотографиями для газет")',
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "User canceled" in result.stderr:
            return jsonify({"ok": True, "cancelled": True})
        return jsonify({"error": result.stderr.strip() or "Не удалось выбрать папку"}), 500

    folder = Path(result.stdout.strip()).expanduser().resolve()
    if not folder.is_dir():
        return jsonify({"error": "Выбранная папка не найдена"}), 400
    with _gazety_watch_lock:
        _gazety_watch["folder"] = folder
        _gazety_watch["files"] = {}
    return jsonify({"ok": True, "folder": str(folder), "files": _gazety_scan_watch_folder()})


@app.route("/api/gazety/watch/files")
def api_gazety_watch_files():
    with _gazety_watch_lock:
        folder = _gazety_watch["folder"]
    if not folder:
        return jsonify({"error": "Папка отслеживания не выбрана"}), 400
    return jsonify({"ok": True, "folder": str(folder), "files": _gazety_scan_watch_folder()})


@app.route("/api/gazety/watch/file/<file_id>")
def api_gazety_watch_file(file_id):
    with _gazety_watch_lock:
        path = _gazety_watch["files"].get(file_id)
    if not path or not path.is_file():
        abort(404)
    response = send_file(str(path))
    response.headers["Cache-Control"] = "no-store"
    return response


def _gazety_update_dims(asset_id: str, w: int, h: int):
    gazety_dir = _gazety_dir()
    for n in (2, 3, 4, 5):
        p = gazety_dir / f"data{n}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text("utf-8"))
        changed = False
        for asset in d.get("assets", []):
            if asset.get("id") == asset_id:
                asset["w"] = w
                asset["h"] = h
                changed = True
        if changed:
            p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


@app.route("/api/gazety/info")
def api_gazety_info():
    gazety_dir = _gazety_dir()
    imgs = {}
    for slot, fname in _GAZETY_SLOTS.items():
        p = gazety_dir / "images" / fname
        imgs[slot] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
    return jsonify({"folder": str(gazety_dir), "exists": gazety_dir.exists(), "images": imgs, "versions": [2, 3, 4, 5]})


@app.route("/api/gazety/images/<filename>")
def api_gazety_image(filename):
    allowed = set(_GAZETY_SLOTS.values())
    if filename not in allowed:
        abort(404)
    f = _gazety_dir() / "images" / filename
    if not f.exists():
        abort(404)
    resp = send_file(str(f))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/gazety/photo_src")
def api_gazety_photo_src():
    gazety_dir = _gazety_dir()
    orig = gazety_dir / "images" / "_img_1_original.jpg"
    curr = gazety_dir / "images" / "img_1.jpg"
    src = orig if orig.exists() else curr
    if not src.exists():
        abort(404)
    resp = send_file(str(src))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/gazety/data/<int:n>")
def api_gazety_data(n):
    import time as _t
    if n not in (2, 3, 4, 5):
        abort(404)
    p = _gazety_dir() / f"data{n}.json"
    if not p.exists():
        abort(404)
    d = json.loads(p.read_text("utf-8"))
    ts = int(_t.time())
    for asset in d.get("assets", []):
        if asset.get("u") == "images/" and asset.get("p"):
            asset["u"] = "/api/gazety/images/"
            asset["p"] = asset["p"] + "?t=" + str(ts)
    return jsonify(d)


@app.route("/api/gazety/replace/<slot>", methods=["POST"])
def api_gazety_replace(slot):
    if slot not in _GAZETY_SLOTS:
        abort(400)
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    gazety_dir = _gazety_dir()
    dest = gazety_dir / "images" / _GAZETY_SLOTS[slot]
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    if slot == "img_1":
        orig = gazety_dir / "images" / "_img_1_original.jpg"
        shutil.copy2(str(dest), str(orig))
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(dest)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and "," in r.stdout.strip():
            w, h = map(int, r.stdout.strip().split(","))
            asset_id = "image_" + slot.split("_")[1]
            _gazety_update_dims(asset_id, w, h)
    except Exception:
        pass
    return jsonify({"ok": True, "slot": slot})


@app.route("/api/gazety/apply_photo", methods=["POST"])
def api_gazety_apply_photo():
    d = request.get_json(silent=True) or {}
    zoom  = min(3.0, max(0.25, float(d.get("zoom", 1.0))))
    x_off = int(d.get("x", 0))
    y_off = int(d.get("y", 0))

    FW, FH = 1920, 1080
    gazety_dir = _gazety_dir()
    src = gazety_dir / "images" / "_img_1_original.jpg"
    if not src.exists():
        src = gazety_dir / "images" / "img_1.jpg"
    if not src.exists():
        return jsonify({"error": "img_1 not found"}), 404

    flt = (
        f"color=c=black:s={FW}x{FH}:d=1[canvas];"
        f"[0:v]scale=w='iw*max({FW}/iw\\,{FH}/ih)*{zoom}':"
        f"h='ih*max({FW}/iw\\,{FH}/ih)*{zoom}':flags=lanczos,setsar=1[scaled];"
        f"[canvas][scaled]overlay=(W-w)/2+{x_off}:(H-h)/2+{y_off}[out]"
    )
    dest = gazety_dir / "images" / "img_1.jpg"
    tmp  = gazety_dir / "images" / "_img_1_apply_tmp.jpg"

    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-loop", "1", "-i", str(src),
        "-filter_complex", flt,
        "-map", "[out]", "-frames:v", "1", "-q:v", "2",
        str(tmp),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return jsonify({"error": r.stderr.decode()[-300:]}), 500

    tmp.replace(dest)
    _gazety_update_dims("image_1", FW, FH)
    return jsonify({"ok": True})


@app.route("/api/gazety/save_render", methods=["POST"])
def api_gazety_save_render():
    import base64 as _b64, time as _t
    d = request.get_json(silent=True) or {}
    version    = int(d.get("version", 2))
    frames_b64 = d.get("frames", [])
    blur       = float(d.get("blur", 0))
    project    = (d.get("project") or "").strip()

    if not frames_b64:
        return jsonify({"error": "no frames"}), 400
    if not project:
        return jsonify({"error": "project not specified"}), 400

    out_dir = _data_dir() / project / "placeholders_screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Save browser-captured PNG frames (with alpha channel)
    frame_paths = []
    for i, b64 in enumerate(frames_b64):
        data = _b64.b64decode(b64.split(",", 1)[-1])
        fp = tmp_dir / f"f{i}.png"
        fp.write_bytes(data)
        frame_paths.append(fp)

    ts = int(_t.time())
    out_file = out_dir / f"gazeta_v{version}_{ts}.mov"
    n = len(frame_paths)

    # Pass 1: blend frames + optional blur → intermediate PNG (preserves alpha)
    if n > 1 or blur > 0:
        blended = tmp_dir / "blended.png"
        fparts = []
        if n > 1:
            cur = "0"
            for i in range(1, n):
                nxt = f"b{i}"
                fparts.append(f"[{cur}][{i}]blend=all_mode=average[{nxt}]")
                cur = nxt
            last = cur
        else:
            last = "0"
        if blur > 0:
            fparts.append(f"[{last}]boxblur={max(1, int(blur))}:1[out]")
            out_label = "out"
        else:
            out_label = last
        blend_cmd = ["ffmpeg", "-y", "-nostdin"]
        for fp in frame_paths:
            blend_cmd += ["-i", str(fp)]
        blend_cmd += ["-filter_complex", ";".join(fparts), "-map", f"[{out_label}]",
                      "-frames:v", "1", str(blended)]
        r = subprocess.run(blend_cmd, capture_output=True)
        if r.returncode != 0:
            return jsonify({"error": r.stderr.decode()[-400:]}), 500
        src = blended
    else:
        src = frame_paths[0]

    # Pass 2: encode still image as 10-second ProRes 4444 with alpha
    prores_cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-loop", "1", "-i", str(src),
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-r", "25",
        "-t", "10",
        str(out_file),
    ]
    r = subprocess.run(prores_cmd, capture_output=True)

    for fp in frame_paths:
        try: fp.unlink()
        except: pass
    try: (tmp_dir / "blended.png").unlink()
    except: pass

    if r.returncode != 0:
        return jsonify({"error": r.stderr.decode()[-400:]}), 500

    return jsonify({"ok": True, "file": out_file.name})


def _gazety_render_dir(render_id: str) -> Path:
    try:
        uuid.UUID(render_id)
    except (ValueError, TypeError):
        abort(400)
    return Path(_settings["base_dir"]) / ".gazety_render" / render_id


def _find_command(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError(f"{name} не найден. Установите его через Homebrew.")


@app.route("/api/gazety/render/start", methods=["POST"])
def api_gazety_render_start():
    d = request.get_json(silent=True) or {}
    project = (d.get("project") or "").strip()
    version = int(d.get("version", 2))
    fps = max(1, min(60, int(d.get("fps", 25))))
    frame_count = max(1, min(2000, int(d.get("frame_count", 250))))
    output_name = Path(str(d.get("output_name") or "")).stem
    output_name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]+", "_", output_name).strip("._-")[:80]

    if not project:
        return jsonify({"error": "project not specified"}), 400
    if version not in (2, 3, 4, 5):
        return jsonify({"error": "invalid version"}), 400

    render_id = str(uuid.uuid4())
    render_dir = _gazety_render_dir(render_id)
    render_dir.mkdir(parents=True, exist_ok=False)
    (render_dir / "meta.json").write_text(json.dumps({
        "project": project,
        "version": version,
        "fps": fps,
        "frame_count": frame_count,
        "output_name": output_name,
    }), encoding="utf-8")
    return jsonify({"ok": True, "render_id": render_id})


@app.route("/api/gazety/render/<render_id>/frame/<int:index>", methods=["POST"])
def api_gazety_render_frame(render_id, index):
    render_dir = _gazety_render_dir(render_id)
    meta_file = render_dir / "meta.json"
    if not meta_file.exists():
        abort(404)
    meta = json.loads(meta_file.read_text("utf-8"))
    if index < 0 or index >= meta["frame_count"]:
        abort(400)
    frame = request.files.get("frame")
    if not frame:
        return jsonify({"error": "frame not specified"}), 400
    frame.save(str(render_dir / f"f{index:04d}.png"))
    return jsonify({"ok": True})


@app.route("/api/gazety/render/<render_id>/finish", methods=["POST"])
def api_gazety_render_finish(render_id):
    import time as _t

    render_dir = _gazety_render_dir(render_id)
    meta_file = render_dir / "meta.json"
    if not meta_file.exists():
        abort(404)
    meta = json.loads(meta_file.read_text("utf-8"))
    frame_count = meta["frame_count"]
    missing = [i for i in range(frame_count) if not (render_dir / f"f{i:04d}.png").exists()]
    if missing:
        return jsonify({"error": f"missing frames: {len(missing)}"}), 400

    out_dir = _data_dir() / meta["project"] / "placeholders_screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    name_part = f"_{meta['output_name']}" if meta.get("output_name") else ""
    out_file = out_dir / f"gazeta_v{meta['version']}{name_part}_{_t.time_ns()}.mov"

    cmd = [
        _find_command("ffmpeg"), "-y", "-nostdin",
        "-framerate", str(meta["fps"]),
        "-start_number", "0",
        "-i", str(render_dir / "f%04d.png"),
    ]
    cmd += [
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-r", str(meta["fps"]),
        str(out_file),
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        shutil.rmtree(render_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 500
    with _gazety_render_lock:
        if render_id in _gazety_cancelled_renders:
            process.terminate()
        _gazety_render_processes[render_id] = process
    stdout, stderr = process.communicate()
    with _gazety_render_lock:
        _gazety_render_processes.pop(render_id, None)
        cancelled = render_id in _gazety_cancelled_renders
        _gazety_cancelled_renders.discard(render_id)
    shutil.rmtree(render_dir, ignore_errors=True)
    try:
        render_dir.parent.rmdir()
    except OSError:
        pass
    if cancelled:
        try:
            out_file.unlink()
        except OSError:
            pass
        return jsonify({"error": "render cancelled", "cancelled": True}), 409
    if process.returncode != 0:
        return jsonify({"error": stderr.decode("utf-8", "ignore")[-600:]}), 500
    return jsonify({"ok": True, "file": out_file.name})


@app.route("/api/gazety/render/<render_id>/cancel", methods=["POST"])
def api_gazety_render_cancel(render_id):
    render_dir = _gazety_render_dir(render_id)
    with _gazety_render_lock:
        _gazety_cancelled_renders.add(render_id)
        process = _gazety_render_processes.get(render_id)
        if process and process.poll() is None:
            process.terminate()
    shutil.rmtree(render_dir, ignore_errors=True)
    return jsonify({"ok": True, "cancelled": True})


# ── SSE stream ─────────────────────────────────────────────────────────────────
@app.route("/api/stream")
def api_stream():
    def generate():
        last_seq = int(request.args.get("since") or 0)
        while True:
            with _job_condition:
                deadline = time.time() + 25
                while True:
                    events = [event for event in (_current_job.get("events") or []) if int(event.get("seq") or 0) > last_seq]
                    if events:
                        break
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        events = [{"type": "ping", "seq": last_seq}]
                        break
                    _job_condition.wait(timeout=remaining)

            for item in events:
                last_seq = max(last_seq, int(item.get("seq") or last_seq))
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") == "done":
                    return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status")
def api_status():
    with _job_condition:
        return jsonify(_job_status_locked())


# ── Free port ──────────────────────────────────────────────────────────────────
def find_free_port(start: int = 7420, end: int = 7499) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Нет свободного порта в диапазоне 7420–7499")


# ── macOS tray ─────────────────────────────────────────────────────────────────
def _start_tray(port: int):
    try:
        import rumps  # type: ignore
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory  # type: ignore
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except ImportError:
            pass

        class _App(rumps.App):
            def __init__(self):
                super().__init__("📹", quit_button=None)
                self.menu = [
                    rumps.MenuItem("Открыть интерфейс", callback=self._open),
                    None,
                    rumps.MenuItem("Остановить", callback=self._stop),
                ]

            def _open(self, _):
                webbrowser.open(f"http://localhost:{port}")

            def _stop(self, _):
                _remove_pid_file()
                os._exit(0)

        _App().run()
    except ImportError:
        import time
        print("Установите rumps для иконки в трее: pip install rumps")
        while True:
            time.sleep(60)


# ── Entry point ────────────────────────────────────────────────────────────────
def _remove_pid_file():
    pid_file = os.environ.get("OSNOVATELI_PID_FILE")
    if not pid_file:
        return
    try:
        Path(pid_file).unlink()
    except OSError:
        pass


def main():
    atexit.register(_remove_pid_file)
    port = find_free_port()
    url = f"http://localhost:{port}"

    print("=== OSNOVATELI.DOC Web Interface ===")
    print(f"URL: {url}")
    print("Нажмите Ctrl+C для остановки\n")

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=False,
        name="flask-server",
    )
    server_thread.start()

    def _open():
        import time
        time.sleep(0.8)
        webbrowser.open(url)

    if os.environ.get("OSNOVATELI_OPEN_BROWSER", "1") != "0":
        threading.Thread(target=_open, daemon=True).start()
    try:
        _start_tray(port)
    except Exception as exc:
        print(f"⚠️  Трей не запустился: {exc}")
        server_thread.join()


if __name__ == "__main__":
    main()
