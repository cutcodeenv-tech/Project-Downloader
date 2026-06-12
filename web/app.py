#!/usr/bin/env python3
"""
Веб-интерфейс для osnovateli_doc_framework.
Запуск: python web/app.py
"""
import importlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))

try:
    from flask import Flask, jsonify, render_template, request, Response, stream_with_context
except ImportError:
    print("Flask не установлен. Установите: pip install flask")
    sys.exit(1)

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))

# ── Global state ───────────────────────────────────────────────────────────────
_job_lock = threading.Lock()
_current_job: dict = {"running": False, "log_queue": queue.Queue()}
_settings: dict = {"base_dir": str(BASE_DIR)}


def _data_dir() -> Path:
    return Path(_settings["base_dir"]) / "data"


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
    result["docker"] = {"ok": shutil.which("docker") is not None, "type": "system"}

    compose_ok = False
    if result["docker"]["ok"]:
        try:
            compose_ok = (
                subprocess.run(
                    ["docker", "compose", "version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).returncode
                == 0
            )
        except Exception:
            pass
    result["docker-compose"] = {"ok": compose_ok, "type": "system"}

    return result


# ── Job runner ─────────────────────────────────────────────────────────────────
def _run_job(cmd, env=None, cwd=None):
    q = _current_job["log_queue"]
    q.put({"type": "start", "cmd": " ".join(str(c) for c in cmd)})
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(cwd or BASE_DIR),
            bufsize=1,
        )
        for line in proc.stdout:
            q.put({"type": "log", "text": line.rstrip()})
        proc.wait()
        q.put({"type": "done", "code": proc.returncode})
    except Exception as exc:
        q.put({"type": "error", "text": str(exc)})
        q.put({"type": "done", "code": 1})
    finally:
        _current_job["running"] = False


def _start_job(cmd, env=None, cwd=None):
    with _job_lock:
        if _current_job["running"]:
            return False, "Уже выполняется другая задача"
        _current_job["log_queue"] = queue.Queue()
        _current_job["running"] = True
    threading.Thread(
        target=_run_job, args=(cmd,), kwargs={"env": env, "cwd": cwd}, daemon=True
    ).start()
    return True, "ok"


def _build_env(**kwargs) -> dict:
    env = os.environ.copy()
    env["BASE_DIR"] = _settings["base_dir"]
    bd = Path(_settings["base_dir"])
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(bd / "scripts"), str(bd / "core"), env.get("PYTHONPATH", "")])
    )
    for k, v in kwargs.items():
        if v is not None:
            env[k.upper()] = str(v)
    return env


def _list_projects() -> list:
    d = _data_dir()
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template(
        "index.html",
        settings=_settings,
        projects=_list_projects(),
        deps=check_deps(),
    )


@app.route("/api/deps")
def api_deps():
    return jsonify(check_deps())


@app.route("/api/projects")
def api_projects():
    return jsonify(_list_projects())


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        if "base_dir" in data:
            p = Path(str(data["base_dir"])).expanduser().resolve()
            if not p.exists():
                return jsonify({"error": f"Папка не найдена: {p}"}), 400
            _settings["base_dir"] = str(p)
        return jsonify(_settings)
    return jsonify(_settings)


@app.route("/api/run/install_deps", methods=["POST"])
def api_install_deps():
    req_file = Path(_settings["base_dir"]) / "requirements.txt"
    if not req_file.exists():
        return jsonify({"error": "requirements.txt не найден"}), 400
    ok, msg = _start_job([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_playwright", methods=["POST"])
def api_install_playwright():
    ok, msg = _start_job([sys.executable, "-m", "playwright", "install", "chromium"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/install_ffmpeg", methods=["POST"])
def api_install_ffmpeg():
    main_py = Path(_settings["base_dir"]) / "core" / "main.py"
    ok, msg = _start_job([sys.executable, str(main_py), "--run", "install_ffmpeg"])
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/new_project", methods=["POST"])
def api_run_new_project():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    sheets_url = (data.get("sheets_url") or "").strip()
    image_mode = data.get("image_mode", "crop")
    convert_videos = str(data.get("convert_videos", False)).lower()
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not sheets_url:
        return jsonify({"error": "Укажите ссылку на Google таблицу"}), 400

    main_py = Path(_settings["base_dir"]) / "core" / "main.py"
    env = _build_env(
        project_name=pname,
        image_processing_mode=image_mode,
        spreadsheet_url=sheets_url,
        convert_videos=convert_videos,
    )
    ok, msg = _start_job([sys.executable, str(main_py), "--run", "new_project"], env=env)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/edits", methods=["POST"])
def api_run_edits():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    sheets_url = (data.get("sheets_url") or "").strip()
    image_mode = data.get("image_mode", "crop")
    convert_videos = str(data.get("convert_videos", False)).lower()
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not sheets_url:
        return jsonify({"error": "Укажите ссылку на Google таблицу"}), 400

    main_py = Path(_settings["base_dir"]) / "core" / "main.py"
    env = _build_env(
        project_name=pname,
        image_processing_mode=image_mode,
        spreadsheet_url=sheets_url,
        convert_videos=convert_videos,
    )
    ok, msg = _start_job([sys.executable, str(main_py), "--run", "edits"], env=env)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/run/direct_video", methods=["POST"])
def api_run_direct_video():
    data = request.get_json() or {}
    pname = (data.get("project_name") or "").strip()
    raw_urls = data.get("urls") or []
    urls = [u.strip() for u in raw_urls if str(u).strip().startswith("http")]
    if not pname:
        return jsonify({"error": "Укажите название проекта"}), 400
    if not urls:
        return jsonify({"error": "Укажите хотя бы одну ссылку"}), 400

    main_py = Path(_settings["base_dir"]) / "core" / "main.py"
    env = _build_env(project_name=pname)
    env["VIDEO_URLS"] = "\n".join(urls)
    ok, msg = _start_job([sys.executable, str(main_py), "--run", "direct_video"], env=env)
    return (jsonify({"status": "started"}) if ok else jsonify({"error": msg})), (200 if ok else 409)


@app.route("/api/stream")
def api_stream():
    def generate():
        q = _current_job["log_queue"]
        while True:
            try:
                item = q.get(timeout=25)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") == "done":
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status")
def api_status():
    return jsonify({"running": _current_job["running"]})


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

        class _App(rumps.App):
            def __init__(self):
                super().__init__("📹", quit_button=None)
                self.menu = [
                    rumps.MenuItem("Открыть интерфейс", callback=self._open),
                    None,
                    rumps.MenuItem("Остановить", callback=lambda _: os._exit(0)),
                ]

            def _open(self, _):
                webbrowser.open(f"http://localhost:{port}")

        _App().run()
    except ImportError:
        # rumps not installed — main thread just waits
        import time
        print("Установите rumps для иконки в трее: pip install rumps")
        while True:
            time.sleep(60)


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    port = find_free_port()
    url = f"http://localhost:{port}"

    print("=== OSNOVATELI.DOC Web Interface ===")
    print(f"URL: {url}")
    print("Нажмите Ctrl+C для остановки\n")

    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    ).start()

    # open browser after Flask starts
    def _open():
        import time
        time.sleep(0.8)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    _start_tray(port)


if __name__ == "__main__":
    main()
