#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime


PROJECT_MARKER_FILENAME = ".osnovateli-project.json"

# Раскладка папок проекта по шаблону монтажа: материал группируется по типу,
# а не по стадии пайплайна. Ключ — внутреннее имя папки в коде, значение —
# путь относительно корня проекта.
ADMIN_DIR = "00_Admin"
PROJECT_FILES_DIR = "01_Project_Files"
SOURCES_DIR = "02_Sources"

PROJECT_FOLDERS = {
    "database": f"{ADMIN_DIR}/database",
    "errors": f"{ADMIN_DIR}/errors",

    "voiceover": f"{SOURCES_DIR}/Audio",

    "placeholders_xml": f"{SOURCES_DIR}/Graphics/Placeholders",
    "articles": f"{SOURCES_DIR}/Graphics/Web",
    "author": f"{SOURCES_DIR}/Graphics/Photo",
    "filmstrips": f"{SOURCES_DIR}/Graphics/Filmstrips",
    "filmstrip_videos": f"{SOURCES_DIR}/Graphics/Filmstrips_video",
    "gazety_direct": f"{SOURCES_DIR}/Graphics/Web Animate",

    "images": f"{SOURCES_DIR}/Images",
    "images_cropped": f"{SOURCES_DIR}/Images/Cropped",

    "video": f"{SOURCES_DIR}/Video/YT",
    "renamed_videos": f"{SOURCES_DIR}/Video/Renamed",
    "video_motionarray": f"{SOURCES_DIR}/Video/MotionArray",
    "video_direct": f"{SOURCES_DIR}/Video/Direct",
}

# Пустые папки шаблона под проектные файлы монтажных программ.
TEMPLATE_EXTRA_DIRS = tuple(
    f"{PROJECT_FILES_DIR}/{app}"
    for app in ("AfterEffects", "Audition", "DaVinci", "Illustrator", "Photoshop", "Premiere")
)

# Имена папок, по которым опознаётся папка проекта. Старые названия оставлены,
# чтобы проекты, сделанные до перехода на шаблон, продолжали находиться в меню.
_LEGACY_STRUCTURE_DIRS = (
    "01_структура_и_метаданные",
    "02_скачивание_и_подготовка",
    "03_упаковка",
    "database",
    "images",
    "video",
    "renamed_videos",
    "placeholders_xml",
)

PROJECT_STRUCTURE_DIRS = (ADMIN_DIR, PROJECT_FILES_DIR, SOURCES_DIR) + _LEGACY_STRUCTURE_DIRS


def project_subdir(project_dir, name: str) -> Path:
    """Путь к рабочей подпапке проекта по карте PROJECT_FOLDERS."""
    project_dir = Path(project_dir)
    relative = PROJECT_FOLDERS.get(name)
    if relative is None:
        return project_dir / name
    return project_dir.joinpath(*relative.split("/"))


def get_base_dir(current_file: str) -> Path:
    env_base_dir = os.getenv("BASE_DIR")
    if env_base_dir:
        return Path(env_base_dir).expanduser().resolve()

    file_path = Path(current_file).resolve()
    if file_path.parent.name == "service":
        return file_path.parent.parent.parent
    return file_path.parent.parent


def get_data_dir(current_file: str) -> Path:
    env_projects_root = os.getenv("PROJECTS_ROOT") or os.getenv("DATA_DIR")
    if env_projects_root:
        return Path(env_projects_root).expanduser().resolve()
    return get_base_dir(current_file) / "data"


def get_projects_root(current_file: str) -> Path:
    return get_data_dir(current_file)


def get_assets_dir(current_file: str) -> Path:
    env_assets_dir = os.getenv("ASSETS_DIR")
    if env_assets_dir:
        return Path(env_assets_dir).expanduser().resolve()
    return get_base_dir(current_file) / "assets"


def get_assets_media_dir(current_file: str) -> Path:
    env_assets_media_dir = os.getenv("ASSETS_MEDIA_DIR")
    if env_assets_media_dir:
        return Path(env_assets_media_dir).expanduser().resolve()
    return get_base_dir(current_file) / "assets_media"


def get_scripts_dir(current_file: str) -> Path:
    return get_base_dir(current_file) / "scripts"


def get_project_dir(current_file: str, project_name: str) -> Path:
    return get_data_dir(current_file) / project_name


def get_project_marker_path(project_dir: Path) -> Path:
    return Path(project_dir) / PROJECT_MARKER_FILENAME


def is_project_dir(path: Path) -> bool:
    marker = get_project_marker_path(path)
    if marker.exists():
        return True
    if not path.is_dir():
        return False
    return any((path / dirname).exists() for dirname in PROJECT_STRUCTURE_DIRS)


def read_project_marker(project_dir: Path) -> dict:
    marker = get_project_marker_path(project_dir)
    if not marker.exists():
        return {}
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_project_marker(project_dir: Path, payload: dict) -> dict:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["project_path"] = str(project_dir.resolve())
    payload["updated_at"] = payload.get("updated_at") or datetime.now().isoformat(timespec="seconds")
    marker = get_project_marker_path(project_dir)
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def ensure_project_marker(project_dir: Path, project_name: str | None = None, *, base_dir: Path | None = None, projects_root: Path | None = None) -> dict:
    project_dir = Path(project_dir).expanduser().resolve()
    marker = read_project_marker(project_dir)
    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        "schema_version": 1,
        "project_name": project_name or marker.get("project_name") or project_dir.name,
        "project_path": str(project_dir),
        "base_dir": str(base_dir.resolve()) if base_dir else marker.get("base_dir", ""),
        "projects_root": str(projects_root.resolve()) if projects_root else marker.get("projects_root", ""),
        "created_at": marker.get("created_at", now),
        "updated_at": now,
        "status": marker.get("status", "new"),
        "current_flow": marker.get("current_flow", ""),
        "last_run_at": marker.get("last_run_at", ""),
        "current_wave": marker.get("current_wave", ""),
        "pending_steps": marker.get("pending_steps", []),
        "paused_flow": marker.get("paused_flow", ""),
        "paused_image_mode": marker.get("paused_image_mode", ""),
        "paused_wave": marker.get("paused_wave", ""),
        "spreadsheet_url": marker.get("spreadsheet_url", ""),
        "spreadsheet_id": marker.get("spreadsheet_id", ""),
        "spreadsheet_attached_at": marker.get("spreadsheet_attached_at", ""),
        "last_spreadsheet_url": marker.get("last_spreadsheet_url", ""),
        "last_spreadsheet_id": marker.get("last_spreadsheet_id", ""),
        "last_spreadsheet_mode": marker.get("last_spreadsheet_mode", ""),
        "last_spreadsheet_updated_at": marker.get("last_spreadsheet_updated_at", ""),
        "spreadsheet_history": marker.get("spreadsheet_history", []),
        "source_file": marker.get("source_file", ""),
        "table_source_kind": marker.get("table_source_kind", ""),
        "steps": marker.get("steps", {}),
        "notes": marker.get("notes", ""),
    }
    return write_project_marker(project_dir, payload)


def list_projects(projects_root: Path) -> list[dict]:
    projects_root = Path(projects_root).expanduser().resolve()
    if not projects_root.exists():
        return []
    items: list[dict] = []
    for child in sorted((p for p in projects_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        if not is_project_dir(child):
            continue
        marker = ensure_project_marker(child)
        steps = marker.get("steps") or {}
        done_count = sum(1 for step in steps.values() if (step or {}).get("status") == "done")
        failed_count = sum(1 for step in steps.values() if (step or {}).get("status") == "failed")
        running_count = sum(1 for step in steps.values() if (step or {}).get("status") == "running")
        items.append({
            "name": marker.get("project_name") or child.name,
            "path": str(child),
            "updated_at": marker.get("updated_at", ""),
            "status": marker.get("status", "new"),
            "current_flow": marker.get("current_flow", ""),
            "current_wave": marker.get("current_wave", ""),
            "spreadsheet_url": marker.get("spreadsheet_url", ""),
            "spreadsheet_id": marker.get("spreadsheet_id", ""),
            "has_spreadsheet": bool(marker.get("spreadsheet_url") or marker.get("spreadsheet_id")),
            "done_steps": done_count,
            "failed_steps": failed_count,
            "running_steps": running_count,
            "marker_path": str(get_project_marker_path(child)),
        })
    return items


def resolve_project_name() -> str:
    project_name = (os.getenv("PROJECT_NAME") or "").strip()
    if project_name:
        return project_name

    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("❌ Название проекта не может быть пустым!")
