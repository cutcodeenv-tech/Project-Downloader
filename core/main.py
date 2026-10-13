import os
import re
import csv
import json
import sys
import time
import shutil
import platform
import importlib
import subprocess
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None

try:
    import gspread
except ImportError:
    gspread = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from google.oauth2.service_account import Credentials
except ImportError:
    Credentials = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    import questionary
    from questionary import Choice
    QUESTIONARY_STYLE = questionary.Style([
        ("qmark", "fg:#00d7ff bold"),
        ("question", "bold"),
        ("answer", "fg:#00d7ff bold"),
        ("pointer", "fg:#00d7ff bold"),
        ("highlighted", "fg:#00d7ff bold"),
        ("selected", "fg:#00d7ff"),
        ("instruction", "fg:#808080"),
        ("text", ""),
    ])
except ImportError:
    questionary = None
    Choice = None
    QUESTIONARY_STYLE = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


FORBIDDEN_SOURCE_URL = "https://www.youtube.com/@osnovatelidoc"
REQUEST_TIMEOUT = 20
SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}
DEFAULT_VIDEO_DOWNLOAD_PAUSE_SECONDS = 4.0
DEFAULT_YTDLP_RETRY_COUNT = 3
DEFAULT_YTDLP_RETRY_BASE_SECONDS = 5.0


def is_shorts_url(url: str) -> bool:
    return '/shorts/' in url


def clean_url(url: str) -> str:
    """Убирает list= из URL если есть конкретное видео (v=), чтобы не качать плейлист."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if 'v' in qs and 'list' in qs:
        qs.pop('list')
        qs.pop('index', None)
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    return url


class Logger:
    def __init__(self):
        self.stats = {
            "youtube": {"success": 0, "error": 0},
            "unknown_host": 0,
            "empty_host": 0,
        }

    def _write(self, level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"INFO": "\033[36m", "ERROR": "\033[31m", "WARN": "\033[33m", "SUCCESS": "\033[32m"}
        reset = "\033[0m"
        print(f"{colors.get(level, '')}[{timestamp}] [{level}]{reset} {message}")
        sys.stdout.flush()

    def info(self, msg): self._write("INFO", msg)
    def warning(self, msg): self._write("WARN", msg)
    def success(self, msg): self._write("SUCCESS", msg)


DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(os.getenv("BASE_DIR", str(DEFAULT_BASE_DIR))).resolve()
ENV_FILE = str(BASE_DIR / '.env')
SCRIPTS_DIR = BASE_DIR / 'scripts'
REQUIREMENTS_FILE = BASE_DIR / 'requirements.txt'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

if load_dotenv is not None and os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=False)

from settings import (apply_settings_to_env, set_setting, SETTINGS_FIELDS, SETTINGS_FIELD_MAP,
                      load_scan_folders, add_scan_folder, remove_scan_folder, clean_path_value)
apply_settings_to_env(__file__)

_projects_root_raw = clean_path_value(os.getenv("PROJECTS_ROOT") or os.getenv("DATA_DIR") or "")
DATA_DIR = str(Path(_projects_root_raw or (BASE_DIR / "data")).expanduser().resolve())
DEFAULT_DATA_DIR = DATA_DIR

from path_utils import ensure_project_marker, read_project_marker, write_project_marker, list_projects, project_subdir, get_assets_dir, PROJECT_FOLDERS, TEMPLATE_EXTRA_DIRS
import table_source
from youtube_utils import is_downloadable_youtube_video


WHISPER_MODEL_DEFAULT = "mlx-community/whisper-large-v3-turbo"
WHISPER_MODEL_FALLBACK = "base"


# Project structure creation function
_REQUIRED_ASSETS = [
    "font/theater.bold-condensed.ttf",
]


def _check_assets() -> None:
    """Проверяет наличие asset-файлов. Предупреждает, но не останавливает пайплайн."""
    assets_dir = get_assets_dir(__file__)
    missing = [p for p in _REQUIRED_ASSETS if not (assets_dir / p).exists()]
    if not missing:
        return
    print("\n\033[33m⚠️  Отсутствуют asset-файлы (некоторые скрипты не будут работать):\033[0m")
    for p in missing:
        print(f"   • {assets_dir / p}")
    print(f"\033[33m   Положите их в папку: {assets_dir}\033[0m")
    print("\033[33m   (или укажите свою через переменную окружения ASSETS_DIR)\033[0m\n")


def get_project_dir(project_name: str) -> Path:
    return Path(DATA_DIR) / project_name


def set_active_projects_root(path) -> str:
    """Корень проектов на время одного действия меню: проект может лежать
    вне стандартной папки, а стадии и подпроцессы читают DATA_DIR/PROJECTS_ROOT."""
    global DATA_DIR
    DATA_DIR = str(Path(path).expanduser().resolve())
    os.environ["PROJECTS_ROOT"] = DATA_DIR
    return DATA_DIR


def reset_active_projects_root() -> None:
    set_active_projects_root(DEFAULT_DATA_DIR)


def init_project_state(project_name: str) -> dict:
    return ensure_project_marker(
        get_project_dir(project_name),
        project_name=project_name,
        base_dir=BASE_DIR,
        projects_root=Path(DATA_DIR),
    )


def update_project_state(project_name: str, mutate) -> dict:
    project_dir = get_project_dir(project_name)
    state = ensure_project_marker(
        project_dir,
        project_name=project_name,
        base_dir=BASE_DIR,
        projects_root=Path(DATA_DIR),
    )
    mutate(state)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return write_project_marker(project_dir, state)


def attach_project_spreadsheet(project_name: str, spreadsheet_url: str, spreadsheet_id: str, mode: str) -> dict:
    spreadsheet_url = (spreadsheet_url or "").strip()
    spreadsheet_id = (spreadsheet_id or "").strip()
    mode = (mode or "stage_parse_links").strip()
    now = datetime.now().isoformat(timespec="seconds")

    def mutate(state):
        history = list(state.get("spreadsheet_history") or [])
        if not history or (
            history[-1].get("spreadsheet_id") != spreadsheet_id
            or history[-1].get("mode") != mode
        ):
            history.append({
                "spreadsheet_url": spreadsheet_url,
                "spreadsheet_id": spreadsheet_id,
                "mode": mode,
                "attached_at": now,
            })
        state.update({
            "spreadsheet_url": spreadsheet_url,
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_attached_at": state.get("spreadsheet_attached_at") or now,
            "last_spreadsheet_url": spreadsheet_url,
            "last_spreadsheet_id": spreadsheet_id,
            "last_spreadsheet_mode": mode,
            "last_spreadsheet_updated_at": now,
            "spreadsheet_history": history[-20:],
        })

    return update_project_state(project_name, mutate)


def create_structure():
    def resolve_project_name():
        env_name = os.getenv("PROJECT_NAME", "").strip()
        if env_name:
            return env_name

        while True:
            name = input('Введите название проекта: ').strip()
            if not name:
                print('Ошибка: название проекта не может быть пустым.')
                continue
            return name

    _check_assets()

    project_name = resolve_project_name()
    project_dir = get_project_dir(project_name)

    is_new = not project_dir.exists()
    project_dir.mkdir(parents=True, exist_ok=True)
    print(f'Создана директория проекта: {project_dir}' if is_new else f'Проект уже существует: {project_dir}')

    for folder_name in PROJECT_FOLDERS:
        project_subdir(project_dir, folder_name).mkdir(parents=True, exist_ok=True)
    for relative in TEMPLATE_EXTRA_DIRS:
        project_dir.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)

    init_project_state(project_name)

    return project_name


# Link parsing function
def parse_links(project_name):
    load_dotenv(ENV_FILE, override=True)

    project_dir = os.path.join(DATA_DIR, project_name)
    database_dir = str(project_subdir(project_dir, 'database'))
    os.makedirs(database_dir, exist_ok=True)

    service_account_env_keys = [
        "TYPE",
        "PROJECT_ID",
        "PRIVATE_KEY_ID",
        "PRIVATE_KEY",
        "CLIENT_EMAIL",
        "CLIENT_ID",
        "AUTH_URI",
        "TOKEN_URI",
        "AUTH_PROVIDER_X509_CERT_URL",
        "CLIENT_X509_CERT_URL",
        "UNIVERSE_DOMAIN",
    ]

    def get_env_value(key):
        return (os.getenv(key) or "").strip()

    def get_service_account_info():
        missing = [key for key in service_account_env_keys if not get_env_value(key)]
        if missing:
            print("\n\033[31mОшибка: не заполнены переменные сервисного аккаунта Google.\033[0m")
            print(f"Файл настроек: {ENV_FILE}")
            print("Отсутствуют значения: " + ", ".join(missing))
            email = get_env_value("CLIENT_EMAIL")
            if email:
                print(f"Email сервисного аккаунта: {email}")
            raise RuntimeError("Заполните .env и запустите шаг «Парсинг Google таблицы» повторно.")

        return {
            "type": get_env_value("TYPE"),
            "project_id": get_env_value("PROJECT_ID"),
            "private_key_id": get_env_value("PRIVATE_KEY_ID"),
            "private_key": get_env_value("PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": get_env_value("CLIENT_EMAIL"),
            "client_id": get_env_value("CLIENT_ID"),
            "auth_uri": get_env_value("AUTH_URI"),
            "token_uri": get_env_value("TOKEN_URI"),
            "auth_provider_x509_cert_url": get_env_value("AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": get_env_value("CLIENT_X509_CERT_URL"),
            "universe_domain": get_env_value("UNIVERSE_DOMAIN"),
        }

    def check_if_reparse(spreadsheet_url):
        input_link_file = os.path.join(database_dir, 'input_link.csv')
        if not os.path.exists(input_link_file):
            return False
        try:
            with open(input_link_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('url') == spreadsheet_url:
                        return True
        except Exception as e:
            print(f"Ошибка при чтении input_link.csv: {e}")
        return False

    def save_input_link_info(spreadsheet_url, spreadsheet_id, is_reparse):
        input_link_file = os.path.join(database_dir, 'input_link.csv')
        timestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        if is_reparse:
            with open(input_link_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([spreadsheet_url, spreadsheet_id, timestamp])
        else:
            with open(input_link_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['url', 'spreadsheet_id', 'created_at'])
                writer.writerow([spreadsheet_url, spreadsheet_id, timestamp])
        print(f"Информация о ссылке сохранена: {spreadsheet_url}")

    def resolve_worksheet(sh):
        for title in ['Лист1', 'Sheet1', 'Sheet', 'Лист']:
            try:
                return sh.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                pass
        try:
            return sh.sheet1
        except Exception:
            pass
        worksheets = sh.worksheets()
        titles = [ws.title for ws in worksheets]
        print("Доступные листы: " + ", ".join(titles))
        while True:
            user_title = input("Введите название листа: ").strip()
            if not user_title:
                continue
            try:
                return sh.worksheet(user_title)
            except gspread.exceptions.WorksheetNotFound:
                print("Лист не найден, попробуйте снова.")

    def extract_spreadsheet_id_from_url():
        # Non-interactive mode: read from env var (set by web UI)
        env_url = os.getenv("SPREADSHEET_URL", "").strip()
        if env_url:
            m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', env_url)
            if m:
                return env_url, m.group(1)
        while True:
            url = input("Введите ссылку на Google таблицу: ").strip()
            if not url:
                print("Ошибка: ссылка не может быть пустой.")
                continue
            match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
            if match:
                return url, match.group(1)
            print("Ошибка: не удалось извлечь SPREADSHEET_ID из ссылки.")

    def fetch_sheet_values(spreadsheet_id, service_account_info):
        scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = resolve_worksheet(sh)
        return worksheet.get_all_values()

    def dump_table(all_values, is_reparse):
        if is_reparse:
            timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
            filename = f'input_gdoc_{timestamp}.csv'
        else:
            filename = 'input_gdoc.csv'

        filepath = os.path.join(database_dir, filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(all_values)

        print(f"Структура таблицы сохранена в: {filename} ({len(all_values)} строк)")
        return filename

    def extract_links_from_columns(rows, resolved_columns=None):
        """resolved_columns=None — сканируем все колонки подряд."""
        all_links = []
        for row_num, row in enumerate(rows, 1):
            if resolved_columns is None:
                cells = [(table_source.column_letter(i), value) for i, value in enumerate(row)]
            else:
                cells = [(letter, row[i]) for i, letter, _spec in resolved_columns if i < len(row)]
            for letter, value in cells:
                cell = str(value).strip()
                if not cell:
                    continue
                for idx, url in enumerate(re.findall(r'https?://[^\s,;"\'<>]+', cell), 1):
                    all_links.append({
                        'source_address': f"{letter}{row_num}_{idx}",
                        'url': url,
                    })
        print(f"Найдено {len(all_links)} ссылок")
        return all_links

    def link_columns_override(rows):
        """Обычно None (все колонки). Сузить можно переменной LINK_COLUMNS."""
        specs = table_source.parse_columns_spec(os.getenv("LINK_COLUMNS", ""))
        if not specs:
            return None
        resolved = table_source.resolve_columns(rows, specs, 1)
        print(f"Колонки для поиска ссылок: {table_source.describe_columns(resolved)}")
        return resolved

    def resolve_source_file(project_dir, state):
        declared = (state.get("source_file") or "").strip()
        if declared:
            explicit = Path(project_dir) / declared
            if explicit.exists():
                return explicit
            print(f"⚠️  Указанный в маркере проекта файл не найден: {explicit}")
        return table_source.find_local_source(project_dir)

    def choose_table_source(project_name, project_dir, state):
        """Возвращает файл-источник либо None (значит Google таблица).

        Порядок: переменная окружения → запомненный выбор → вопрос в меню →
        прежнее автоопределение.
        """
        if (os.getenv("SPREADSHEET_URL") or "").strip():
            return None

        found = resolve_source_file(project_dir, state)
        remembered = (state.get("table_source_kind") or "").strip()

        if remembered == "sheets":
            return None
        if remembered == "file" and found:
            return found

        if can_use_interactive_menu():
            options = [("Google таблица", "sheets")]
            if found:
                options.append((f"Файл в папке проекта — {found.name}", "file"))
            else:
                print(f"\nВ папке проекта нет CSV/XLSX: {project_dir}")
            kind = select_option("Откуда берём таблицу?", options)
            update_project_state(project_name, lambda st: st.update({"table_source_kind": kind}))
            return found if kind == "file" else None

        return found

    def announce_reparse(is_reparse):
        if is_reparse:
            print("ВНИМАНИЕ: Повторный парсинг. Новые данные будут добавлены после строк upd_<дата>")
        else:
            print("Первый парсинг этого источника")

    def is_youtube_url(url):
        return 'youtube.com' in url or 'youtu.be' in url

    def is_motionarray_url(url):
        return 'motionarray.com' in url

    def is_image_url(url):
        image_domains = [
            'images.app.goo.gl', 'avatars.mds.yandex.net', 'avatars.dzeninfra.ru',
            'cdn.i.haymarketmedia.asia', 'images.steamusercontent.com',
            'play-lh.googleusercontent.com', 'share.google'
        ]
        if any(d in url for d in image_domains):
            return True
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']
        if any(url.lower().split('?')[0].endswith(ext) for ext in image_exts):
            return True
        if any(p in url for p in ['scale_', 'resize', 'XXXL', 'diploma', 'thumbs']):
            return True
        return False

    def is_video_url(url):
        video_domains = [
            'vimeo.com', 'vk.com/video', 'rutube.ru', 'dailymotion.com',
            'tiktok.com', 'facebook.com', 'bilibili.com', 'ok.ru', 'dzen.ru', 'instagram.com'
        ]
        if any(d in url for d in video_domains):
            return True
        if 'yandex.ru/video' in url:
            return True
        video_exts = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.m4v', '.3gp']
        if any(url.lower().split('?')[0].endswith(ext) for ext in video_exts):
            return True
        return False

    def check_content_type(url):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                ct = response.headers.get('content-type', '').lower()
                if 'image/' in ct:
                    return 'image'
                if 'video/' in ct:
                    return 'video'
        except Exception:
            pass
        return None

    def categorize_url(url):
        if is_youtube_url(url) and not is_shorts_url(url):
            return 'youtube'
        if is_motionarray_url(url):
            return 'motionarray'
        if is_image_url(url):
            return 'image'
        if is_video_url(url):
            return 'video'
        return check_content_type(url) or 'other'

    def get_existing_urls(filepath):
        existing = set()
        if not os.path.exists(filepath):
            return existing
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2 and not row[0].startswith('upd_') and row[1].strip():
                        existing.add(row[1].strip())
        except Exception as e:
            print(f"Ошибка при чтении существующих ссылок: {e}")
        return existing

    def save_links_to_csv(all_links, is_reparse):
        filepath = os.path.join(database_dir, f'os_doc_{project_name}_all_links.csv')
        if is_reparse and os.path.exists(filepath):
            existing = get_existing_urls(filepath)
            new_links = [l for l in all_links if l['url'] not in existing]
            if new_links:
                timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
                with open(filepath, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([f'upd_{timestamp}', ''])
                    for l in new_links:
                        writer.writerow([l['source_address'], l['url']])
                print(f"Добавлено {len(new_links)} новых ссылок в os_doc_{project_name}_all_links.csv")
            else:
                print("Новых ссылок не обнаружено")
        else:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['source_address', 'url'])
                for l in all_links:
                    writer.writerow([l['source_address'], l['url']])
            print(f"Сохранено {len(all_links)} ссылок в os_doc_{project_name}_all_links.csv")

    def categorize_and_save(all_links, is_reparse):
        categories = {'image': [], 'youtube': [], 'motionarray': [], 'video': [], 'other': []}
        for link in all_links:
            category = categorize_url(link['url'])
            categories[category].append(link)
            print(f"[{category.upper()}] {link['source_address']}: {link['url']}")

        timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
        for category, links in categories.items():
            if not links:
                continue
            filepath = os.path.join(database_dir, f'os_doc_{project_name}_{category}_links.csv')
            if is_reparse and os.path.exists(filepath):
                existing = get_existing_urls(filepath)
                new_links = [l for l in links if l['url'] not in existing]
                if new_links:
                    with open(filepath, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([f'upd_{timestamp}', ''])
                        for l in new_links:
                            writer.writerow([l['source_address'], l['url']])
                    print(f"Добавлено {len(new_links)} новых ссылок [{category}]")
            else:
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['source_address', 'url'])
                    for l in links:
                        writer.writerow([l['source_address'], l['url']])
                print(f"Сохранено {len(links)} ссылок [{category}]")
        return categories

    print(f"Проект: {project_name}")

    state = read_project_marker(project_dir)
    source_file = choose_table_source(project_name, project_dir, state)

    if source_file:
        print(f"Источник: файл {source_file.name}")
        is_reparse = check_if_reparse(str(source_file))
        announce_reparse(is_reparse)
        save_input_link_info(str(source_file), source_file.name, is_reparse)
        all_values = table_source.read_table(source_file)
        update_project_state(project_name, lambda st: st.update({"source_file": source_file.name}))
    else:
        service_account_info = get_service_account_info()
        service_email = service_account_info["client_email"]
        print(f"\n\033[33mДайте данному email доступ 'Читатель' к таблице:\n{service_email}\033[0m\n")
        spreadsheet_url, spreadsheet_id = extract_spreadsheet_id_from_url()
        attach_project_spreadsheet(project_name, spreadsheet_url, spreadsheet_id, os.getenv("FLOW_NAME", "stage_parse_links"))
        is_reparse = check_if_reparse(spreadsheet_url)
        announce_reparse(is_reparse)
        save_input_link_info(spreadsheet_url, spreadsheet_id, is_reparse)
        all_values = fetch_sheet_values(spreadsheet_id, service_account_info)

    dump_table(all_values, is_reparse)
    all_links = extract_links_from_columns(all_values, link_columns_override(all_values))
    save_links_to_csv(all_links, is_reparse)
    categorize_and_save(all_links, is_reparse)

    # Сразу генерируем pulltube_links.txt и motionarray_links.txt
    _generate_pulltube_links(database_dir, project_name, is_reparse)
    _generate_motionarray_links(database_dir, project_name, is_reparse)



def _generate_pulltube_links(database_dir: str, project_name: str, is_reparse: bool) -> None:
    """Создаёт/обновляет pulltube_links.txt из os_doc_*_youtube_links.csv."""
    csv_file = os.path.join(database_dir, f'os_doc_{project_name}_youtube_links.csv')
    if not os.path.exists(csv_file):
        print("⚠️  YouTube CSV не найден, pulltube_links.txt не создан")
        return

    csv_links: list[str] = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get('url') or '').strip()
                # Только конкретные видео: каналы / шортсы / плейлисты пропускаем.
                if url and is_downloadable_youtube_video(url):
                    csv_links.append(clean_url(url))
    except Exception as e:
        print(f"⚠️  Ошибка чтения YouTube CSV: {e}")
        return

    if not csv_links:
        print("⚠️  В YouTube CSV нет ссылок, pulltube_links.txt не создан")
        return

    pulltube_file = os.path.join(database_dir, 'pulltube_links.txt')

    if is_reparse and os.path.exists(pulltube_file):
        with open(pulltube_file, 'r', encoding='utf-8') as f:
            existing = {l.strip() for l in f if l.strip()}
        new_links = [u for u in csv_links if u not in existing]
        if not new_links:
            print("✓ pulltube_links.txt актуален, новых YouTube-ссылок нет")
            return
        timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
        out_file = os.path.join(database_dir, f'pulltube_links_{timestamp}.txt')
        with open(out_file, 'w', encoding='utf-8') as f:
            f.writelines(u + '\n' for u in new_links)
        print(f"✓ Создан {os.path.basename(out_file)} с {len(new_links)} новыми YouTube-ссылками")
    else:
        with open(pulltube_file, 'w', encoding='utf-8') as f:
            f.writelines(u + '\n' for u in csv_links)
        print(f"✓ Создан pulltube_links.txt с {len(csv_links)} YouTube-ссылками")


def _generate_motionarray_links(database_dir: str, project_name: str, is_reparse: bool) -> None:
    """Создаёт/обновляет motionarray_links.txt из os_doc_*_motionarray_links.csv."""
    csv_file = os.path.join(database_dir, f'os_doc_{project_name}_motionarray_links.csv')
    if not os.path.exists(csv_file):
        print("⚠️  MotionArray CSV не найден, motionarray_links.txt не создан")
        return

    csv_links: list[str] = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get('url') or '').strip()
                if url:
                    csv_links.append(url)
    except Exception as e:
        print(f"⚠️  Ошибка чтения MotionArray CSV: {e}")
        return

    if not csv_links:
        print("⚠️  В MotionArray CSV нет ссылок, motionarray_links.txt не создан")
        return

    ma_file = os.path.join(database_dir, 'motionarray_links.txt')

    if is_reparse and os.path.exists(ma_file):
        with open(ma_file, 'r', encoding='utf-8') as f:
            existing = {l.strip() for l in f if l.strip()}
        new_links = [u for u in csv_links if u not in existing]
        if not new_links:
            print("✓ motionarray_links.txt актуален, новых ссылок нет")
            return
        timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
        out_file = os.path.join(database_dir, f'motionarray_links_{timestamp}.txt')
        with open(out_file, 'w', encoding='utf-8') as f:
            f.writelines(u + '\n' for u in new_links)
        print(f"✓ Создан {os.path.basename(out_file)} с {len(new_links)} новыми MotionArray-ссылками")
    else:
        with open(ma_file, 'w', encoding='utf-8') as f:
            f.writelines(u + '\n' for u in csv_links)
        print(f"✓ Создан motionarray_links.txt с {len(csv_links)} MotionArray-ссылками")


def _sanitize_channel_name(channel: str) -> str:
    channel = (channel or "").strip()
    if not channel or FORBIDDEN_SOURCE_URL in channel:
        return ""
    return channel


def _cookies_from_browser_tuple(value: str):
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    parts = [part.strip() or None for part in cleaned.split(":")]
    while len(parts) < 4:
        parts.append(None)
    return tuple(parts[:4])


def _metadata_from_ytdlp(url: str, logger) -> Tuple[str, str]:
    if yt_dlp is None:
        return "", ""

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": REQUEST_TIMEOUT,
    }
    cookies_file = get_cookies_file()
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    cookies_from_browser = _cookies_from_browser_tuple(get_cookies_from_browser())
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = cookies_from_browser

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        logger.warning(f"yt-dlp metadata failed: {url} ({exc})")
        return "", ""

    if not isinstance(info, dict):
        return "", ""

    channel = ""
    for key in ("channel", "uploader", "creator", "artist", "uploader_id", "channel_id"):
        channel = _sanitize_channel_name(str(info.get(key) or ""))
        if channel:
            break
    title = str(info.get("title") or "").strip()
    if channel:
        logger.success(f"{url} -> {channel} (yt-dlp)")
    return channel, title


def _retry_after_seconds(response, attempt: int) -> float:
    """Сколько ждать перед повтором после 429. Уважает Retry-After, иначе экспонента."""
    header = (response.headers.get("Retry-After") or "").strip()
    if header.isdigit():
        return min(float(header), 60.0)
    return min(2.0 * (attempt + 1), 30.0)


def _fetch_json(session, url, retries: int = 3):
    """GET с парсингом JSON. На 429 делает backoff и повторяет (устойчивость при 1000+ ссылок)."""
    for attempt in range(max(1, retries)):
        try:
            response = session.get(url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                if attempt + 1 < retries:
                    time.sleep(_retry_after_seconds(response, attempt))
                    continue
                return None
            if response.status_code >= 400:
                return None
            return response.json()
        except Exception:
            return None
    return None


def get_channel_and_title_for_url(session, url, logger):
    """Возвращает (channel, title) для YouTube URL."""
    try:
        match = re.match(r"^https?://([^/]+)", url, flags=re.IGNORECASE)
        host = match.group(1).lower().replace("www.", "") if match else ""
    except Exception:
        host = ""

    if not host:
        logger.stats["empty_host"] += 1
        return "", ""
    if "youtube.com" not in host and host != "youtu.be":
        logger.stats["unknown_host"] += 1
        return "", ""

    try:
        oembed_url = "https://www.youtube.com/oembed?format=json&url=" + requests.utils.quote(url, safe="")
        payload = _fetch_json(session, oembed_url)
        if payload and payload.get("author_name"):
            channel = _sanitize_channel_name(str(payload["author_name"]))
            title = (payload.get("title") or "").strip()
            logger.stats["youtube"]["success"] += 1
            if channel:
                logger.success(f"{url} -> {channel}")
            return channel, title
        logger.stats["youtube"]["error"] += 1
    except Exception:
        pass

    channel, title = _metadata_from_ytdlp(url, logger)
    if channel:
        logger.stats["youtube"]["success"] += 1
        return channel, title
    return "", title


# Channel enrichment function
def enrich_channels(project_name: str):
    database_dir = str(project_subdir(os.path.join(DATA_DIR, project_name), 'database'))

    def load_cache(cache_file):
        cache = {}
        if not os.path.exists(cache_file):
            return cache
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    url = row.get('url', '').strip()
                    if url:
                        cache[url] = (
                            row.get('channel', '').strip(),
                            row.get('title', '').strip(),
                        )
        except Exception:
            pass
        return cache

    def save_cache(cache, cache_file):
        with open(cache_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['url', 'channel', 'title'])
            for url, (channel, title) in cache.items():
                writer.writerow([url, channel, title])

    csv_file = os.path.join(database_dir, f'os_doc_{project_name}_youtube_links.csv')
    if not os.path.exists(csv_file):
        print("Файл youtube_links.csv не найден, обогащение каналов пропущено.")
        return

    links: List[Tuple[str, str]] = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                src = row.get('source_address', '').strip()
                url = row.get('url', '').strip()
                if src and url and not src.startswith('upd_'):
                    links.append((src, url))
    except Exception as e:
        print(f"Ошибка при чтении youtube_links.csv: {e}")
        return

    if not links:
        print("Ссылок для обогащения не найдено.")
        return

    from progress_ui import render_bar, StatusBoard

    cache_file = os.path.join(database_dir, 'channel_cache.csv')
    cache = load_cache(cache_file)
    logger = Logger()
    session = requests.Session()
    results: List[Tuple[str, str, str, str]] = []  # (source_address, url, channel, title)

    total = len(links)
    board = StatusBoard(2)
    for idx, (source_address, url) in enumerate(links, 1):
        overall = (idx - 1) / max(total, 1)
        board.render([
            f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {idx - 1}/{total})",
            f"Канал:  {url}",
        ])
        if url in cache:
            channel, title = cache[url]
            if channel:
                results.append((source_address, url, channel, title))
                continue
        channel, title = get_channel_and_title_for_url(session, url, logger)
        cache[url] = (channel, title)
        results.append((source_address, url, channel, title))
        time.sleep(0.12)
    board.render([
        f"Всего:  [{render_bar(1.0)}] 100.0%  (готово: {total}/{total})",
        "",
    ])
    board.close()

    save_cache(cache, cache_file)

    output_file = os.path.join(database_dir, f'os_doc_{project_name}_channels.csv')
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['source_address', 'url', 'channel', 'title'])
        for row in results:
            writer.writerow(row)

    found = sum(1 for _, _, ch, _ in results if ch)
    print(f"Каналов найдено: {found}/{len(results)}")


# Voiceover transcription function (feeds stage_xml with a ready *.words.json)
def _find_voiceover_audio(voiceover_dir: Path):
    for ext in ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.ogg"):
        matches = sorted(voiceover_dir.glob(ext))
        if matches:
            return matches[-1]
    return None


def _find_words_json(voiceover_dir: Path):
    matches = sorted(voiceover_dir.glob("*.words.json"))
    return matches[-1] if matches else None


def _has_transcript(voiceover_dir: Path) -> bool:
    return bool(_find_words_json(voiceover_dir) or list(voiceover_dir.glob("*.srt")) or list(voiceover_dir.glob("*.txt")))


def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _pip_install(package: str) -> bool:
    print(f"⬇️  {package} не найден — устанавливаю...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--prefer-binary", package],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"❌ Не удалось установить {package}:\n{(r.stderr or r.stdout)[-400:]}")
        return False
    print(f"✅ {package} установлен")
    return True


def _install_whisper() -> str:
    """Возвращает движок транскрипции: 'mlx' (быстрый, Apple Silicon),
    'openai' (везде) или '' если ничего не удалось поставить."""
    if _apple_silicon():
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            if _pip_install("mlx-whisper"):
                return "mlx"
            print("⚠️  Откатываюсь на openai-whisper (медленнее).")

    try:
        import whisper  # noqa: F401
        return "openai"
    except ImportError:
        pass
    return "openai" if _pip_install("openai-whisper") else ""


def transcribe_voiceover(project_name: str):
    """Транскрибирует озвучку из voiceover/ через Whisper (пословные
    таймкоды) в <файл>.words.json — источник для шага текстового оверлея
    (stage_xml), который сам транскрипцию больше не делает. Пропускается,
    если расшифровка уже есть или в voiceover/ нет аудио."""
    voiceover_dir = project_subdir(get_project_dir(project_name), "voiceover")

    if _has_transcript(voiceover_dir):
        print("♻️  Расшифровка в voiceover/ уже есть — транскрипция пропущена.")
        return

    audio_path = _find_voiceover_audio(voiceover_dir)
    if not audio_path:
        print(f"⏭️  Транскрипция пропущена: нет аудио в {voiceover_dir}.")
        return "skipped"

    if not ask_confirm(f"Транскрибировать {audio_path.name} через Whisper сейчас?", default=True):
        print("\n⏭️  Транскрипция пропущена — запустите Стадию 1 ещё раз, когда понадобится.")
        return "skipped"

    engine = _install_whisper()
    if not engine:
        raise RuntimeError("Не удалось установить движок транскрипции.")

    model_name = os.getenv("WHISPER_MODEL", "").strip()
    language = os.getenv("WHISPER_LANGUAGE", "").strip()

    if engine == "mlx":
        model_name = model_name or WHISPER_MODEL_DEFAULT
    else:
        # На openai-whisper имена MLX-репозиториев не работают
        if not model_name or "/" in model_name:
            model_name = WHISPER_MODEL_FALLBACK

    print(f"🎙  Транскрибирую (по словам): {audio_path.name}")
    print(f"    Движок: {'MLX (Apple Silicon)' if engine == 'mlx' else 'openai-whisper'}")
    print(f"    Модель: {model_name}  Язык: {language or 'авто'}")

    opts = {"word_timestamps": True}
    if language:
        opts["language"] = language

    if engine == "mlx":
        import mlx_whisper
        result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model_name, **opts)
    else:
        import whisper
        result = whisper.load_model(model_name).transcribe(str(audio_path), verbose=False, **opts)

    segments = []
    for seg in result.get("segments", []):
        words = [
            {"word": w.get("word", "").strip(), "start": float(w["start"]), "end": float(w["end"])}
            for w in (seg.get("words") or [])
            if w.get("word", "").strip()
        ]
        segments.append({
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": (seg.get("text") or "").strip(),
            "words": words,
        })

    out_path = voiceover_dir / f"{audio_path.stem}.words.json"
    out_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Транскрипция сохранена: {out_path}")


# XML placeholders creation function
def _has_voiceover_material(project_name: str) -> bool:
    voiceover_dir = project_subdir(get_project_dir(project_name), "voiceover")
    patterns = ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.ogg", "*.words.json", "*.srt", "*.txt")
    return any(list(voiceover_dir.glob(p)) for p in patterns)


def create_xml_placeholders(project_name: str):
    has_material = _has_voiceover_material(project_name)
    prompt = "Делаем текстовый оверлей (плейсхолдеры) сейчас?"
    if not has_material:
        prompt += " Озвучки в voiceover/ пока не видно — можно пропустить и запустить этот шаг позже (Стадия 1 ещё раз, когда добавите аудио)."
    if not ask_confirm(prompt, default=has_material):
        print("\n⏭️  Текстовый оверлей пропущен — запустите Стадию 1 ещё раз, когда появится озвучка.")
        return "skipped"

    script_path = SCRIPTS_DIR / "1.2_xml_placeholders.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Скрипт не найден: {script_path}")
    review_script = SCRIPTS_DIR / "text_overlay_align" / "helpers" / "review_matches.py"
    matches_path = project_subdir(get_project_dir(project_name), "placeholders_xml") / "_work" / "matches.json"

    from progress_ui import run_quiet

    env = build_script_env(project_name=project_name)
    result = run_quiet([sys.executable, script_path], cwd=str(BASE_DIR), env=env, title="Текстовый оверлей")
    if result.ok:
        return
    if result.returncode != 3:
        raise RuntimeError(f"Команда завершилась с ошибкой: {result.returncode}")

    # Exit code 3 = "needs review": some rows are ambiguous (several
    # candidate matches) or unmatched (none found). Run the interactive
    # reviewer right here, in this same terminal, with real stdin -- the
    # quiet subprocess runner above can't do that (its stdin is /dev/null).
    print("\nЕсть строки, которые нужно подтвердить вручную:\n")
    subprocess.run([sys.executable, str(review_script), "--matches", str(matches_path)], cwd=str(BASE_DIR), env=env)

    # Re-run: TEXT_OVERLAY_FORCE=1 means proceed no matter what's still
    # left unresolved after that one review pass (skipped rows just won't
    # get a card) instead of blocking again.
    force_env = dict(env, TEXT_OVERLAY_FORCE="1")
    run_command([sys.executable, script_path], cwd=BASE_DIR, env=force_env, title="Текстовый оверлей")


_GEOLOGICA_FONT_PATH = get_assets_dir(__file__) / "Design Preparation" / "FONT" / "Geologica" / "Geologica-VariableFont_CRSV,SHRP,slnt,wght.ttf"
_SOURCE_CLARIFY_TEXT = "уточнить источник"


def _load_author_font(size: int):
    for path in [str(_GEOLOGICA_FONT_PATH), "/System/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _make_author_png(channel_name: str, output_path: Path):
    """Создаёт PNG-плашку 1920×1080 с источником канала."""
    if not channel_name or FORBIDDEN_SOURCE_URL in channel_name:
        img = Image.new('RGB', (1920, 1080), color='white')
        draw = ImageDraw.Draw(img)
        font = _load_author_font(80)
        bbox = draw.textbbox((0, 0), _SOURCE_CLARIFY_TEXT, font=font)
        x = (1920 - (bbox[2] - bbox[0])) // 2
        y = (1080 - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), _SOURCE_CLARIFY_TEXT, fill=(0, 0, 0), font=font)
        img.save(output_path, 'PNG')
    else:
        normalized = re.sub(r'\s+', ' ', channel_name.strip())
        source_text = f"Источник: youtube-канал «{normalized}»"
        font = _load_author_font(30)
        img = Image.new('RGBA', (1920, 1080), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((50, 1080 - 50), source_text, fill=(255, 255, 255), font=font, anchor="ls")
        img.save(output_path, 'PNG')


def find_ytdlp_bin() -> str:
    """yt-dlp рядом с текущим интерпретатором важнее того, что в PATH:
    в PATH может висеть старая системная сборка, а YouTube ломает
    совместимость со старыми версиями (403 на скачивании данных)."""
    local = Path(sys.executable).parent / "yt-dlp"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("yt-dlp") or ""


def resolve_video_quality(value: str | None) -> str:
    quality = (value or "").strip().lower()
    if quality in {"original", "1080", "720"}:
        return quality
    return "original"


def yt_dlp_format_for_quality(quality: str) -> str:
    quality = resolve_video_quality(quality)
    if quality == "1080":
        return "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]"
    if quality == "720":
        return "bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best[height<=720]"
    return "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


def _env_float(name: str, default: float) -> float:
    try:
        value = float((os.getenv(name) or "").strip())
        return value if value >= 0 else default
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
        return value if value >= 1 else default
    except Exception:
        return default


def get_video_download_pause_seconds() -> float:
    return _env_float("VIDEO_DOWNLOAD_PAUSE_SECONDS", DEFAULT_VIDEO_DOWNLOAD_PAUSE_SECONDS)


def get_ytdlp_retry_count() -> int:
    return _env_int("YTDLP_RETRY_COUNT", DEFAULT_YTDLP_RETRY_COUNT)


def get_ytdlp_retry_base_seconds() -> float:
    return _env_float("YTDLP_RETRY_BASE_SECONDS", DEFAULT_YTDLP_RETRY_BASE_SECONDS)


def get_cookies_from_browser() -> str:
    for env_name in ("COOKIES_FROM_BROWSER", "YTDLP_COOKIES_FROM_BROWSER"):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value
    return ""


def get_cookies_file() -> Optional[str]:
    configured = (os.getenv("COOKIES_FILE") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return str(path) if path.exists() else None
    default_path = BASE_DIR / "cookies.txt"
    return str(default_path) if default_path.exists() else None


def is_ytdlp_rate_limited(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "429" in lowered
        or "too many requests" in lowered
        or "rate limit" in lowered
        or "http error 429" in lowered
    )


_DOWNLOAD_PROGRESS_RE = re.compile(
    r"\[download\]\s+([\d.]+)%(?:\s+of\s+~?([\d.]+\S+))?(?:\s+at\s+(\S+))?(?:\s+ETA\s+(\S+))?"
)
_DESTINATION_RE = re.compile(r"\[download\] Destination:\s+(.+)$")
_MERGE_RE = re.compile(r'Merging formats into "(.+)"$')


def _download_video_direct(
    url: str,
    output_dir: Path,
    cookies_file: Optional[str] = None,
    board=None,
    idx: int = 1,
    total: int = 1,
    initial_label: str = "",
) -> bool:
    """Скачивает одно видео через yt-dlp subprocess с явным захватом вывода."""
    from progress_ui import render_bar, StatusBoard

    output_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_bin = find_ytdlp_bin()
    board_owned = board is None
    board = board or StatusBoard(3)

    if not ytdlp_bin:
        board.log("  ❌ yt-dlp не найден ни в окружении проекта, ни в PATH")
        return False
    video_quality = resolve_video_quality(os.getenv("VIDEO_QUALITY"))
    cookies_from_browser = get_cookies_from_browser()
    retry_count = get_ytdlp_retry_count()
    retry_base_sleep = get_ytdlp_retry_base_seconds()

    def build_cmd() -> list[str]:
        cmd = [
            ytdlp_bin,
            "--format", yt_dlp_format_for_quality(video_quality),
            "--merge-output-format", "mp4",
            "--output", str(output_dir / "%(title)s [%(id)s].%(ext)s"),
            "--no-playlist",
            "--newline",
        ]
        if cookies_from_browser:
            cmd += ["--cookies-from-browser", cookies_from_browser]
        if cookies_file and Path(cookies_file).exists():
            cmd += ["--cookies", cookies_file]
        cmd.append(url)
        return cmd

    board.log(f"  🎞️ Качество: {video_quality}")
    if cookies_from_browser:
        board.log(f"  🍪 cookies-from-browser: {cookies_from_browser}")
    elif cookies_file and Path(cookies_file).exists():
        board.log(f"  🍪 cookies.txt: {Path(cookies_file).name}")

    # Снимок до скачивания: определяем именно новый файл, чтобы не зависеть
    # от ранее лежавших в папке роликов.
    existing_before = set(output_dir.glob("*.mp4"))

    label = initial_label or url
    file_fraction = 0.0
    file_size = ""
    file_speed = ""
    file_eta = ""

    def redraw():
        overall = ((idx - 1) + file_fraction) / max(total, 1)
        extra = "  ·  ".join(part for part in (file_size, file_speed, f"ETA {file_eta}" if file_eta else "") if part)
        board.render([
            f"Всего:   [{render_bar(overall)}] {overall * 100:5.1f}%  (скачано {idx - 1}/{total}, осталось {max(total - idx + 1, 0)})",
            f"Сейчас:  {label}",
            f"         [{render_bar(file_fraction)}] {file_fraction * 100:5.1f}%" + (f"  {extra}" if extra else ""),
        ])

    redraw()

    for attempt in range(1, retry_count + 1):
        captured_lines: list[str] = []

        # Явно захватываем stdout+stderr и пробрасываем в лог построчно.
        # Это предотвращает переполнение pipe-буфера при наследовании fd от родителя.
        proc = subprocess.Popen(
            build_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            captured_lines.append(line)

            match = _DOWNLOAD_PROGRESS_RE.search(line)
            dest_match = _DESTINATION_RE.search(line) or _MERGE_RE.search(line)
            if match:
                file_fraction = float(match.group(1)) / 100
                file_size = match.group(2) or file_size
                file_speed = match.group(3) or ""
                file_eta = match.group(4) or ""
                redraw()
            elif dest_match:
                label = os.path.basename(dest_match.group(1))
                file_size = file_speed = file_eta = ""
                redraw()
            elif line.startswith("[debug]"):
                continue
            else:
                board.log(f"    {line}")
        proc.wait()

        if proc.returncode == 0:
            new_files = [f for f in output_dir.glob("*.mp4") if f not in existing_before]
            # Если новый файл не обнаружен (например, перекодирование оставило то же имя) —
            # откатываемся на самый свежий mp4 в папке.
            candidates = new_files or list(output_dir.glob("*.mp4"))
            if not candidates:
                board.log(f"  ❌ MP4 файл не найден в {output_dir}")
                if board_owned:
                    board.close()
                return False
            latest = max(candidates, key=lambda f: f.stat().st_mtime)
            size_mb = latest.stat().st_size / 1024 / 1024
            file_fraction = 1.0
            redraw()
            board.log(f"  ✅ Файл: {latest.name} ({size_mb:.1f} MB)")
            if board_owned:
                board.close()
            return True

        joined_output = "\n".join(captured_lines)
        if attempt < retry_count and is_ytdlp_rate_limited(joined_output):
            sleep_for = retry_base_sleep * attempt
            board.log(
                f"  ⚠️ Получен rate limit / 429. Повтор через {sleep_for:.1f} сек "
                f"({attempt}/{retry_count})"
            )
            time.sleep(sleep_for)
            continue

        board.log(f"  ❌ yt-dlp завершился с кодом {proc.returncode}")
        if board_owned:
            board.close()
        return False

    if board_owned:
        board.close()
    return False


# Author image creation function
def create_author_images(project_name: str):

    def sanitize_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def make_output_name(source_address: str, title: str) -> str:
        if title:
            safe_title = sanitize_filename(title)
            return f"{source_address} {safe_title}_author.png"
        return f"{source_address}_author.png"

    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    project_dir = Path(DATA_DIR) / project_name
    channels_csv = project_subdir(project_dir, "database") / f"os_doc_{project_name}_channels.csv"
    base_author_dir = project_subdir(project_dir, "author")
    author_dir = base_author_dir / upd_subdir if upd_subdir else base_author_dir

    if not channels_csv.exists():
        print("⏭️  Файл channels.csv не найден — пропускаю создание плашек источников.")
        return

    data: List[Tuple[str, str, str, str]] = []  # (source_address, url, channel, title)
    try:
        with open(channels_csv, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                src = row.get('source_address', '').strip()
                url = row.get('url', '').strip()
                channel = row.get('channel', '').strip()
                title = row.get('title', '').strip()
                if src and url and not src.startswith('upd_'):
                    data.append((src, url, channel, title))
    except Exception as e:
        print(f"Ошибка при чтении channels.csv: {e}")
        return

    if not data:
        print("Данных для обработки не найдено.")
        return

    author_dir.mkdir(parents=True, exist_ok=True)

    from progress_ui import render_bar, StatusBoard
    from error_log import log_download_error

    created = 0
    skipped = 0
    total = len(data)
    board = StatusBoard(2)
    for idx, (source_address, url, channel_name, title) in enumerate(data, 1):
        overall = (idx - 1) / total
        board.render([
            f"[{idx}/{total}] {source_address}",
            f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {created}, пропущено: {skipped})",
        ])

        output_name = make_output_name(source_address, title)
        output_path = author_dir / output_name
        old_output_path = author_dir / f"{source_address}_author.png"

        # В режиме правок дополнительно проверяем базовую папку
        base_output_path = base_author_dir / output_name
        base_old_output_path = base_author_dir / f"{source_address}_author.png"
        existing_paths = [
            path for path in (output_path, old_output_path, base_output_path, base_old_output_path)
            if path.exists()
        ]
        # output_path уже содержит title в имени (make_output_name) — если он
        # существует, значит эта самая плашка уже собрана именно с текущими
        # данными канала, пересобирать нечего. Остальные existing_paths — это
        # более старые/безымянные варианты (например, плейсхолдер «уточнить
        # источник» до того, как канал определился) — их специально НЕ
        # считаем готовыми, чтобы плашка могла обновиться, когда канал
        # наконец резолвится.
        if output_path.exists():
            skipped += 1
            continue
        if existing_paths and not channel_name:
            skipped += 1
            continue
        try:
            _make_author_png(channel_name, output_path)
            created += 1
        except Exception as e:
            board.log(f"  ❌ {source_address}: {e}")
            log_download_error(project_name, "stage_author", source_address, url, reason=str(e))

    board.render([
        "готово",
        f"Всего:  [{render_bar(1.0)}] 100.0%  (готово: {created}, пропущено: {skipped})",
    ])
    board.close()

    print(f"Создано: {created}, пропущено: {skipped}")


# Image download function (from scripts/2_download_img.py)
def resolve_share_google_url(url):
    if 'share.google/' not in url:
        return url
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        }
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True, stream=True)
        final_url = response.url or url
        response.close()
        try:
            parsed = urlparse(final_url)
            query_params = parse_qs(parsed.query)
            if query_params.get('imgurl'):
                return unquote(query_params['imgurl'][0])
        except Exception:
            pass
        return final_url
    except Exception:
        return url


def extract_google_image_url(url):
    if 'share.google' not in url and 'images.app.goo.gl' not in url:
        return url
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        if query_params.get('imgurl'):
            return unquote(query_params['imgurl'][0])
    except Exception:
        pass
    return url


def get_ext_from_content_type(content_type):
    ct = (content_type or '').lower()
    if 'image/jpeg' in ct or 'image/jpg' in ct:
        return '.jpg'
    if 'image/png' in ct:
        return '.png'
    if 'image/gif' in ct:
        return '.gif'
    if 'image/webp' in ct:
        return '.webp'
    if 'image/bmp' in ct:
        return '.bmp'
    if 'image/tiff' in ct:
        return '.tiff'
    if 'image/svg+xml' in ct:
        return '.svg'
    return None


def get_ext_from_url(url):
    path = urlparse(url).path
    if '.' in path:
        ext = path.split('.')[-1].lower()
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg']:
            return f'.{ext}'
    if 'format=' in url:
        m = re.search(r'format=([^&]+)', url)
        if m and m.group(1).lower() in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            return f'.{m.group(1).lower()}'
    return '.jpg'


def convert_to_jpg(input_path, output_path):
    try:
        with Image.open(input_path) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(output_path, 'JPEG', quality=95, optimize=True)
        return True
    except Exception as e:
        print(f"  Ошибка конвертации: {e}")
        return False


def download_one(url, filename, download_dir):
    if 'share.google/' in url:
        direct_url = resolve_share_google_url(url)
    else:
        direct_url = extract_google_image_url(url)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    last_exc = None
    for attempt in range(3):
        try:
            response = requests.get(direct_url, headers=headers, timeout=30, allow_redirects=True, stream=True)
            if response.status_code != 200:
                print(f"  HTTP {response.status_code} (попытка {attempt + 1}/3)")
                time.sleep(2 ** attempt)
                continue
            content_type = response.headers.get('content-type', '').lower()
            extension = get_ext_from_content_type(content_type) or get_ext_from_url(direct_url)
            final_path = os.path.join(download_dir, f"{filename}.jpg")
            temp_path = os.path.join(download_dir, f"{filename}{extension}")
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if extension.lower() == '.jpg':
                if os.path.abspath(temp_path) != os.path.abspath(final_path):
                    os.replace(temp_path, final_path)
            else:
                if convert_to_jpg(temp_path, final_path):
                    os.remove(temp_path)
                else:
                    print(f"  Сохранено без конвертации: {os.path.basename(temp_path)}")
            return True
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            print(f"  Сеть: {e} (попытка {attempt + 1}/3)")
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Ошибка: {e}")
            return False
    print(f"  Все 3 попытки неудачны: {last_exc}")
    return False


def download_images(project_name: str):
    def get_existing_jpg(base_dir):
        existing = set()
        if not os.path.exists(base_dir):
            return existing
        for f in os.listdir(base_dir):
            if f.endswith('.jpg'):
                existing.add(f.replace('.jpg', ''))
            subpath = os.path.join(base_dir, f)
            if os.path.isdir(subpath):
                for fname in os.listdir(subpath):
                    if fname.endswith('.jpg'):
                        existing.add(fname.replace('.jpg', ''))
        return existing

    def error_placeholder(display_name, download_dir):
        try:
            img = Image.new('RGB', (1920, 1080), color='white')
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 60)
            except Exception:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 60)
                except Exception:
                    font = ImageFont.load_default()
            text = f"download_error {display_name}"
            bbox = draw.textbbox((0, 0), text, font=font)
            x = (1920 - (bbox[2] - bbox[0])) // 2
            y = (1080 - (bbox[3] - bbox[1])) // 2
            draw.text((x, y), text, fill='black', font=font)
            img.save(os.path.join(download_dir, f"{display_name}.jpg"), 'JPEG', quality=95)
            return True
        except Exception:
            return False

    def log_error(display_name, url, pictures_dir):
        from error_log import log_download_error
        log_download_error(project_name, "stage_images", display_name, url)
        error_placeholder(display_name, pictures_dir)

    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    project_dir = os.path.join(DATA_DIR, project_name)
    database_dir = str(project_subdir(project_dir, 'database'))
    base_images_dir = str(project_subdir(project_dir, 'images'))
    pictures_dir = os.path.join(base_images_dir, upd_subdir) if upd_subdir else base_images_dir
    if upd_subdir:
        print(f"Волна правок: {upd_subdir}")
    csv_file = os.path.join(database_dir, f'os_doc_{project_name}_image_links.csv')

    os.makedirs(pictures_dir, exist_ok=True)

    if not os.path.exists(csv_file):
        print("⏭️  Файл image_links.csv не найден — пропускаю скачивание изображений.")
        return

    links = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            src = row.get('source_address', '').strip()
            url = row.get('url', '').strip()
            if src and url and not src.startswith('upd_'):
                links.append({'display_name': src, 'url': url})

    if not links:
        print("Нет ссылок на изображения.")
        return

    existing = get_existing_jpg(base_images_dir)
    to_download = [L for L in links if L['display_name'] not in existing]
    if not to_download:
        print("Все изображения уже скачаны.")
        return

    ok = 0
    fail = 0
    total = len(to_download)

    def _worker(item):
        time.sleep(0.5)  # небольшая пауза чтобы не бомбить сервер
        return item, download_one(item['url'], item['display_name'], pictures_dir)

    from progress_ui import render_bar, StatusBoard

    board = StatusBoard(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_worker, L): L for L in to_download}
        done = 0
        for future in as_completed(futures):
            done += 1
            L, success = future.result()
            if success:
                ok += 1
            else:
                fail += 1
                log_error(L['display_name'], L['url'], pictures_dir)
                board.log(f"  ❌ {L['display_name']}")
            board.render([
                f"Картинки:  [{render_bar(done / total)}] {done / total * 100:5.1f}%  ({done}/{total}, ошибок: {fail})",
            ])
    board.close()

    print(f"Скачано: {ok}, ошибок: {fail}, пропущено (уже есть): {len(links) - len(to_download)}")
    if fail:
        print("Ошибки: errors/stage_2/stage_images.csv")


SCRIPT_TASKS = [
    {
        "id": "smart_cropping",
        "title": "Кроп картинок 16:9",
        "script": "2.1_smart_cropping.py",
        "needs_project": True,
        "needs_image_mode": True,
    },
    {
        "id": "pullvids_download",
        "title": "Скачать YouTube видео (yt-dlp)",
        "script": "3.4_pullvids_download.py",
        "needs_project": True,
    },
    {
        "id": "pulltube_rename",
        "title": "Переименовать YouTube видео",
        "script": "4_pulltube_rename.py",
        "needs_project": True,
        "project_arg": True,
        "continue_on_error": True,
    },
    {
        "id": "motionarray_rename",
        "title": "Переименовать MotionArray видео",
        "script": "4.1_motionarray_rename.py",
        "needs_project": True,
        "project_arg": True,
        "continue_on_error": True,
    },
    {
        "id": "photo_filmstrip",
        "title": "Собрать плёнку с фото (B1-B5, B6-B10, ...)",
        "script": "photo_filmstrip.py",
        "needs_project": True,
        "continue_on_error": True,
    },
    {
        "id": "screenshots",
        "title": "Статьи на рваной бумаге (текст + подсветка заголовка)",
        "script": "website_animate.py",
        "needs_project": True,
        "continue_on_error": True,
    },
    {
        "id": "photo_filmstrip_anim",
        "title": "Анимация плёнки — стол с фото",
        "script": "photo_filmstrip_anim_table.py",
        "needs_project": True,
        "continue_on_error": True,
    },
]

# Стадии проекта: каждый шаг FLOW_STEP_CATALOG принадлежит ровно одной.
# Стадия 1 не зависит ни от чего; стадия 2 использует результат стадии 1
# (ссылки/каналы из таблицы); стадия 3 (упаковка) использует кропнутые
# картинки из стадии 2.
STAGES = [
    {"number": 1, "title": "Структура и метаданные проекта"},
    {"number": 2, "title": "Скачивание и подготовка материала"},
    {"number": 3, "title": "Упаковка"},
]
STAGE_MAP = {stage["number"]: stage for stage in STAGES}

FLOW_STEP_CATALOG = [
    {"id": "stage_structure", "kind": "stage", "title": "Создать структуру папок", "run_mode": "stage_structure", "stage": 1},
    {"id": "stage_parse_links", "kind": "stage", "title": "Парсинг Google таблицы", "run_mode": "stage_parse_links", "needs_sheets": True, "stage": 1},
    {"id": "stage_transcribe", "kind": "stage", "title": "Транскрипция озвучки (Whisper, по словам)", "run_mode": "stage_transcribe", "stage": 1},
    {"id": "stage_xml", "kind": "stage", "title": "Текстовый оверлей (по словам, без склейки)", "run_mode": "stage_xml", "stage": 1},
    {"id": "stage_enrich", "kind": "stage", "title": "Обогащение YouTube-каналов", "run_mode": "stage_enrich", "stage": 1},
    {"id": "stage_images", "kind": "stage", "title": "Скачать изображения", "run_mode": "stage_images", "stage": 2},
    {"id": "pullvids_download", "kind": "script", "title": "Скачать YouTube видео (yt-dlp)", "script_id": "pullvids_download", "stage": 2},
    {"id": "pulltube_rename", "kind": "script", "title": "Переименовать YouTube видео", "script_id": "pulltube_rename", "stage": 2},
    {"id": "motionarray_rename", "kind": "script", "title": "Переименовать MotionArray видео", "script_id": "motionarray_rename", "stage": 2},
    {"id": "smart_cropping", "kind": "script", "title": "Кроп 16:9", "script_id": "smart_cropping", "stage": 2},
    {"id": "stage_author", "kind": "stage", "title": "Создать PNG-плашки источников", "run_mode": "stage_author", "stage": 2},
    {"id": "photo_filmstrip", "kind": "script", "title": "Собрать плёнку с фото (B1-B5, B6-B10, ...)", "script_id": "photo_filmstrip", "stage": 3},
    {"id": "photo_filmstrip_anim", "kind": "script", "title": "Анимация плёнки — стол с фото", "script_id": "photo_filmstrip_anim", "stage": 3},
    {"id": "screenshots", "kind": "script", "title": "Статьи на рваной бумаге (текст + подсветка заголовка)", "script_id": "screenshots", "stage": 3},
]

DEFAULT_NEW_PROJECT_STEP_IDS = [step["id"] for step in FLOW_STEP_CATALOG]


def stage_step_ids(stage_number: int) -> list:
    return [step["id"] for step in FLOW_STEP_CATALOG if step.get("stage") == stage_number]


CORE_PIPELINE_TITLE = "Core pipeline: структура проекта, Google таблица, CSV, XML, авторы, картинки"


def run_command(cmd, cwd=None, env=None, continue_on_error=False, title=None):
    from progress_ui import run_quiet
    label = title or " ".join(str(part) for part in cmd)
    result = run_quiet(cmd, cwd=str(cwd or BASE_DIR), env=env, title=label)
    if not result.ok:
        message = f"Команда завершилась с ошибкой: {result.returncode}"
        if continue_on_error:
            return False
        raise RuntimeError(message)
    return True


def install_python_requirements():
    if not REQUIREMENTS_FILE.exists():
        raise FileNotFoundError(f"Файл requirements.txt не найден: {REQUIREMENTS_FILE}")
    run_command([sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_FILE])
    refresh_optional_imports()


def refresh_optional_imports():
    global requests, gspread, load_dotenv, Credentials, Image, ImageDraw, ImageFont
    global questionary, Choice

    try:
        requests = importlib.import_module("requests")
    except ImportError:
        requests = None

    try:
        gspread = importlib.import_module("gspread")
    except ImportError:
        gspread = None

    try:
        load_dotenv = importlib.import_module("dotenv").load_dotenv
    except ImportError:
        load_dotenv = None

    try:
        Credentials = importlib.import_module("google.oauth2.service_account").Credentials
    except ImportError:
        Credentials = None

    try:
        pil_image = importlib.import_module("PIL.Image")
        pil_image_draw = importlib.import_module("PIL.ImageDraw")
        pil_image_font = importlib.import_module("PIL.ImageFont")
        Image = pil_image
        ImageDraw = pil_image_draw
        ImageFont = pil_image_font
    except ImportError:
        Image = None
        ImageDraw = None
        ImageFont = None

    try:
        questionary = importlib.import_module("questionary")
        Choice = getattr(questionary, "Choice")
    except ImportError:
        questionary = None
        Choice = None


def install_ffmpeg():
    print("\n=== Проверка ffmpeg ===")
    if shutil.which("ffmpeg"):
        print("✓ ffmpeg уже установлен")
        return

    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        run_command(["brew", "install", "ffmpeg"])
        return
    if system == "windows":
        if shutil.which("winget"):
            run_command([
                "winget",
                "install",
                "--id",
                "Gyan.FFmpeg",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ])
            return
        if shutil.which("choco"):
            run_command(["choco", "install", "ffmpeg", "-y"])
            return

    print("⚠️  Не удалось автоматически установить ffmpeg.")
    print("Установите ffmpeg вручную и повторите запуск зависимостей.")


def install_whisper_dependency():
    print("\n=== Проверка движка транскрипции ===")
    engine = _install_whisper()
    if engine == "mlx":
        print("✓ mlx-whisper готов (Apple Silicon)")
    elif engine == "openai":
        print("✓ openai-whisper готов")
    else:
        print("✗ Не удалось поставить движок транскрипции")


def install_node_dependency():
    print("\n=== Проверка Node.js/npm ===")
    if shutil.which("node") and shutil.which("npm"):
        print("✓ node/npm уже установлены")
        return True

    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        run_command(["brew", "install", "node"])
        return shutil.which("node") is not None
    if system == "windows" and shutil.which("winget"):
        run_command(["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e",
                      "--accept-package-agreements", "--accept-source-agreements"])
        return shutil.which("node") is not None

    print("⚠️  Node.js не найден и не установлен автоматически.")
    print("Установите Node.js вручную: https://nodejs.org/ (нужен для стадии 3 — плёнка/статьи через hyperframes)")
    return False


def install_paper_pipeline_dependency():
    """npm install в paper_pipeline/ (puppeteer-core — нужен shot.mjs для статей)."""
    print("\n=== Проверка зависимостей paper_pipeline (статьи) ===")
    paper_dir = BASE_DIR / "paper_pipeline"
    if not paper_dir.exists():
        print("⚠️  paper_pipeline/ не найдена — шаг «Статьи» работать не будет.")
        return
    if not shutil.which("npm"):
        print("⚠️  npm не найден — пропускаю установку зависимостей paper_pipeline.")
        return
    if (paper_dir / "node_modules").exists():
        print("✓ paper_pipeline/node_modules уже установлены")
        return
    run_command(["npm", "install"], cwd=paper_dir, continue_on_error=True)


_CHROME_CANDIDATES = {
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "linux": ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"],
}


def find_chrome_for_puppeteer() -> str | None:
    for path in _CHROME_CANDIDATES.get(platform.system().lower(), []):
        if os.path.exists(path):
            return path
    return None


def check_chrome_for_puppeteer():
    print("\n=== Проверка Google Chrome (для извлечения текста статей) ===")
    found = find_chrome_for_puppeteer()
    if found:
        print(f"✓ Chrome найден: {found}")
        return

    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        run_command(["brew", "install", "--cask", "google-chrome"], continue_on_error=True)
        found = find_chrome_for_puppeteer()
        if found:
            print(f"✓ Chrome установлен: {found}")
            return

    print("⚠️  Google Chrome не найден — шаг «Статьи» (paper_pipeline/shot.mjs) работать не будет.")
    print("Установите Chrome вручную: https://www.google.com/chrome/")


def install_all_dependencies():
    print("\n\033[32m=== Установка всех зависимостей ===\033[0m")
    print(f"Python: {sys.executable}")
    print(f"Version: {platform.python_version()}")
    install_python_requirements()
    install_ffmpeg()
    install_whisper_dependency()
    if install_node_dependency():
        install_paper_pipeline_dependency()
    check_chrome_for_puppeteer()
    print("\n\033[32m=== Зависимости проверены ===\033[0m")


def ensure_core_dependencies():
    missing = []
    if requests is None:
        missing.append("requests")
    if gspread is None:
        missing.append("gspread")
    if load_dotenv is None:
        missing.append("python-dotenv")
    if Credentials is None:
        missing.append("google-auth")
    if Image is None or ImageDraw is None or ImageFont is None:
        missing.append("pillow")

    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Не установлены зависимости для core pipeline: {names}. "
            "Сначала запустите пункт 1 'Установить ВСЕ зависимости'."
        )


def can_use_interactive_menu():
    return questionary is not None and Choice is not None and sys.stdin.isatty()


def select_option(title, options):
    if can_use_interactive_menu():
        answer = questionary.select(
            title,
            choices=[Choice(label, value=value) for label, value in options],
            use_indicator=True,
            style=QUESTIONARY_STYLE,
        ).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer

    print(f"\n=== {title} ===")
    for idx, (label, _value) in enumerate(options, 1):
        print(f"{idx}) {label}")
    while True:
        choice = input("Выберите пункт: ").strip()
        if not choice.isdigit():
            print("Введите номер из списка.")
            continue
        number = int(choice)
        if 1 <= number <= len(options):
            return options[number - 1][1]
        print("Нет пункта с таким номером.")


def ask_text(message):
    if can_use_interactive_menu():
        answer = questionary.text(message, style=QUESTIONARY_STYLE).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer.strip()
    return input(message).strip()


def select_many(title, options, preselected=None):
    """Чек-лист: options — [(label, value)], preselected — какие отмечены сразу."""
    preselected = set(preselected or [])
    if can_use_interactive_menu() and hasattr(questionary, "checkbox"):
        choices = [Choice(label, value=value, checked=value in preselected) for label, value in options]
        answer = questionary.checkbox(title, choices=choices, style=QUESTIONARY_STYLE).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer

    print(f"\n{title}")
    for idx, (label, value) in enumerate(options, 1):
        mark = "x" if value in preselected else " "
        print(f"  {idx}) [{mark}] {label}")
    raw = input("Номера через запятую (пусто — как отмечено): ").strip()
    if not raw:
        return [value for _, value in options if value in preselected]
    picked = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(options):
            picked.append(options[int(part) - 1][1])
    return picked


def ask_confirm(message, default=True):
    if can_use_interactive_menu():
        answer = questionary.confirm(message, default=default, style=QUESTIONARY_STYLE).ask()
        if answer is None:
            raise KeyboardInterrupt
        return bool(answer)
    hint = "Y/n" if default else "y/N"
    answer = input(f"{message} ({hint}): ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "д", "да"}


def project_scan_roots() -> list:
    roots = [Path(DEFAULT_DATA_DIR)]
    for folder in load_scan_folders(__file__):
        path = Path(folder).expanduser()
        if path not in roots:
            roots.append(path)
    return roots


def find_all_projects() -> list:
    """Проекты из стандартного корня и всех запомненных папок."""
    found = []
    seen = set()
    for root in project_scan_roots():
        try:
            if not root.is_dir():
                if root != Path(DEFAULT_DATA_DIR):
                    print(f"⚠️  Папка недоступна, пропускаю: {root}")
                continue
            items = list_projects(root)
        except OSError as exc:
            print(f"⚠️  Не удалось прочитать {root}: {exc}")
            continue
        for item in items:
            key = str(Path(item["path"]).resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(item)
    return sorted(found, key=lambda item: (Path(item["path"]).name.lower(), item["path"]))


def project_menu_options(projects: list) -> list:
    names = [Path(item["path"]).name for item in projects]
    options = []
    for item, name in zip(projects, names):
        label = name if names.count(name) == 1 else f"{name} — {Path(item['path']).parent}"
        options.append((label, item["path"]))
    return options


def activate_project_path(project_path) -> str:
    """Делает папку проекта активной: корнем становится её родитель."""
    project_path = Path(project_path)
    set_active_projects_root(project_path.parent)
    project_name = project_path.name
    os.environ["PROJECT_NAME"] = project_name
    return project_name


def list_existing_projects():
    return sorted({Path(item["path"]).name for item in find_all_projects()})


def select_project_name():
    projects = find_all_projects()
    if projects:
        create_value = "__create_new_project__"
        options = project_menu_options(projects)
        options.append(("Создать новый проект", create_value))
        choice = select_option("Выбор проекта", options)
        if choice != create_value:
            project_name = activate_project_path(choice)
            print(f"Проект: {project_name}")
            return project_name

        while True:
            project_name = ask_text("Введите название нового проекта: ")
            if not project_name:
                print("Название проекта не может быть пустым.")
                continue
            os.environ["PROJECT_NAME"] = project_name
            print(f"Проект: {project_name}")
            return project_name

    while True:
        project_name = ask_text("Введите название нового проекта: ")
        if project_name:
            os.environ["PROJECT_NAME"] = project_name
            print(f"Проект: {project_name}")
            return project_name
        print("Название проекта не может быть пустым.")


def select_image_processing_mode():
    # Остался единственный режим обработки картинок — crop 16:9.
    # (Nano Banana 2 не реализован, опция убрана из интерфейса.)
    os.environ["IMAGE_PROCESSING_MODE"] = "crop"
    return "crop"


def build_script_env(project_name=None, image_mode=None):
    env = os.environ.copy()
    env["BASE_DIR"] = str(BASE_DIR)
    env["PROJECTS_ROOT"] = DATA_DIR
    env["PYTHONUNBUFFERED"] = "1"
    scripts_path = str(SCRIPTS_DIR)
    current_pythonpath = env.get("PYTHONPATH", "")
    paths = [scripts_path]
    if current_pythonpath:
        paths.append(current_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    if project_name:
        env["PROJECT_NAME"] = project_name
    if image_mode:
        env["IMAGE_PROCESSING_MODE"] = image_mode
    upd_subdir = os.getenv("UPD_SUBDIR", "")
    if upd_subdir:
        env["UPD_SUBDIR"] = upd_subdir
    return env


def run_script_task(task, project_name=None, image_mode=None):
    script_path = SCRIPTS_DIR / task["script"]
    if not script_path.exists():
        raise FileNotFoundError(f"Скрипт не найден: {script_path}")

    cmd = [sys.executable, script_path]
    if task.get("project_arg"):
        if not project_name:
            project_name = select_project_name()
        cmd.extend(["--project", project_name])

    return run_command(
        cmd,
        cwd=BASE_DIR,
        env=build_script_env(project_name=project_name, image_mode=image_mode),
        continue_on_error=task.get("continue_on_error", False),
        title=task["title"],
    )

FLOW_STEP_MAP = {step["id"]: step for step in FLOW_STEP_CATALOG}
SCRIPT_TASK_MAP = {task["id"]: task for task in SCRIPT_TASKS}


def get_default_flow_step_ids(flow_name: str):
    if flow_name == "new_project":
        return list(DEFAULT_NEW_PROJECT_STEP_IDS)
    raise RuntimeError(f"Неизвестный flow: {flow_name}")


def normalize_flow_step_ids(flow_name: str, selected_ids):
    allowed_ids = set(get_default_flow_step_ids(flow_name))
    if not selected_ids:
        return get_default_flow_step_ids(flow_name)

    normalized = []
    seen = set()
    for step in FLOW_STEP_CATALOG:
        step_id = step["id"]
        if step_id in selected_ids and step_id in allowed_ids and step_id not in seen:
            normalized.append(step_id)
            seen.add(step_id)
    return normalized


def run_core_stage(run_mode: str, project_name: str):
    os.environ["PROJECT_NAME"] = project_name
    if run_mode == "stage_structure":
        return create_structure()
    if run_mode == "stage_parse_links":
        return parse_links(project_name)
    if run_mode == "stage_transcribe":
        return transcribe_voiceover(project_name)
    if run_mode == "stage_xml":
        return create_xml_placeholders(project_name)
    if run_mode == "stage_enrich":
        return enrich_channels(project_name)
    if run_mode == "stage_author":
        return create_author_images(project_name)
    if run_mode == "stage_images":
        return download_images(project_name)
    raise RuntimeError(f"Неизвестная стадия: {run_mode}")


def execute_flow_steps(project_name: str, image_mode: str, flow_name: str, selected_ids=None):
    ensure_core_dependencies()
    ordered_ids = normalize_flow_step_ids(flow_name, selected_ids or [])
    if not ordered_ids:
        raise RuntimeError("Не выбран ни один шаг для выполнения.")

    os.environ["PROJECT_NAME"] = project_name
    os.environ["FLOW_NAME"] = flow_name
    init_project_state(project_name)
    update_project_state(project_name, lambda state: state.update({
        "status": "running",
        "current_flow": flow_name,
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
        "current_wave": os.getenv("UPD_SUBDIR", "").strip(),
    }))
    from progress_ui import stage_header

    total_steps = len(ordered_ids)
    for step_idx, step_id in enumerate(ordered_ids, 1):
        step = FLOW_STEP_MAP[step_id]
        stage_number = step.get("stage") or 0
        os.environ["STAGE_NUMBER"] = str(stage_number or "")
        stage_title = STAGE_MAP.get(stage_number, {}).get("title", "")
        stage_header(project_name, stage_number, stage_title, step_idx, total_steps, step["title"])
        update_project_state(project_name, lambda state, step_id=step_id, title=step["title"]: state.setdefault("steps", {}).update({
            step_id: {
                "title": title,
                "status": "running",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": "",
                "kind": step["kind"],
            }
        }))
        try:
            step_result = None
            if step["kind"] == "stage":
                step_result = run_core_stage(step["run_mode"], project_name)
            else:
                task = SCRIPT_TASK_MAP[step["script_id"]]
                run_script_task(task, project_name=project_name, image_mode=image_mode)
        except KeyboardInterrupt:
            # Прерванный шаг перезапустится с начала при следующем продолжении
            # (скрипты не гарантируют возобновление с середины) — поэтому
            # remaining включает и сам step_id, а не только то, что после него.
            remaining = ordered_ids[ordered_ids.index(step_id):]
            update_project_state(project_name, lambda state, step_id=step_id: state.setdefault("steps", {}).setdefault(step_id, {}).update({
                "status": "interrupted",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }))
            update_project_state(project_name, lambda state, rem=remaining, fn=flow_name, im=image_mode: state.update({
                "status": "paused",
                "pending_steps": rem,
                "paused_flow": fn,
                "paused_image_mode": im,
                "paused_wave": os.getenv("UPD_SUBDIR", "").strip(),
            }))
            raise
        except Exception:
            update_project_state(project_name, lambda state, step_id=step_id: state.setdefault("steps", {}).setdefault(step_id, {}).update({
                "status": "failed",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }))
            update_project_state(project_name, lambda state: state.update({"status": "failed"}))
            raise
        final_status = "skipped" if step_result == "skipped" else "done"
        update_project_state(project_name, lambda state, step_id=step_id, st=final_status: state.setdefault("steps", {}).setdefault(step_id, {}).update({
            "status": st,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }))

    update_project_state(project_name, lambda state: state.update({
        "status": "ready",
        "pending_steps": [],
        "paused_flow": "",
        "paused_wave": "",
    }))


def ask_new_project_name() -> str:
    """Только ввод имени — списка существующих проектов тут нарочно нет
    (его показывает «Продолжить работу над проектом»)."""
    existing = set(list_existing_projects())
    while True:
        name = ask_text("Введите название нового проекта: ").strip()
        if not name:
            print("Название проекта не может быть пустым.")
            continue
        if name in existing and not ask_confirm(f"Проект «{name}» уже существует. Работать в той же папке?"):
            continue
        os.environ["PROJECT_NAME"] = name
        return name


def ask_project_location(project_name: str) -> Path:
    """Где создать папку проекта: стандартный корень, запомненная папка или свой путь."""
    default_root = Path(DEFAULT_DATA_DIR)
    if not can_use_interactive_menu():
        set_active_projects_root(default_root)
        return default_root

    custom_value = "__custom_path__"
    options = [(f"Стандартная папка — {default_root}", str(default_root))]
    for folder in load_scan_folders(__file__):
        path = Path(folder).expanduser()
        if path != default_root:
            options.append((str(path), str(path)))
    options.append(("Указать свой путь…", custom_value))

    choice = select_option(f"Где создать папку проекта «{project_name}»?", options)

    if choice == custom_value:
        while True:
            answer = ask_text("Путь к папке, внутри которой создать проект: ")
            if not answer:
                print("Путь не может быть пустым.")
                continue
            root = Path(answer).expanduser().resolve()
            if not root.is_dir():
                if not ask_confirm(f"Папки {root} нет. Создать?"):
                    continue
                try:
                    root.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    print(f"Не удалось создать папку: {exc}")
                    continue
            break
        add_scan_folder(root, __file__)
    else:
        root = Path(choice)

    set_active_projects_root(root)
    print(f"Папка проекта: {root / project_name}")
    return root


_STAGE_STATUS_MARK = {"done": "✓", "partial": "…", "pending": " "}


def _artifact_structure(project_name: str) -> bool:
    return project_subdir(get_project_dir(project_name), "database").is_dir()


def _artifact_parse_links(project_name: str) -> bool:
    database_dir = project_subdir(get_project_dir(project_name), "database")
    return (database_dir / f"os_doc_{project_name}_all_links.csv").is_file()


def _artifact_transcribe(project_name: str) -> bool:
    return _has_transcript(project_subdir(get_project_dir(project_name), "voiceover"))


def _artifact_xml(project_name: str) -> bool:
    clips = project_subdir(get_project_dir(project_name), "placeholders_xml") / "overlay_clips"
    return clips.is_dir() and any(clips.iterdir())


def _artifact_enrich(project_name: str) -> bool:
    database_dir = project_subdir(get_project_dir(project_name), "database")
    if (database_dir / f"os_doc_{project_name}_channels.csv").is_file():
        return True
    # Обогащать нечего, если YouTube-ссылок в проекте не было
    return not (database_dir / f"os_doc_{project_name}_youtube_links.csv").is_file()


def _wave_dir(base):
    """Папка текущей волны правок, если она задана."""
    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    return base / upd_subdir if upd_subdir else base


def _expected_filmstrip_pages(project_name: str):
    """Страницы плёнки, которые должны существовать при текущем наборе фото."""
    from photo_filmstrip import group_by_block, build_pages

    cropped = _wave_dir(project_subdir(get_project_dir(project_name), "images_cropped"))
    if not cropped.is_dir():
        return []
    photos = sorted(str(p) for p in cropped.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    if not photos:
        return []
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):   # group_by_block печатает статистику
        return build_pages(group_by_block(photos))


def _artifact_filmstrip(project_name: str) -> bool:
    pages = _expected_filmstrip_pages(project_name)
    if not pages:
        return False
    filmstrips = _wave_dir(project_subdir(get_project_dir(project_name), "filmstrips"))
    return all((filmstrips / f"B{block_id}_p{page_idx}.jpg").is_file()
               for block_id, page_idx, _ in pages)


def _artifact_filmstrip_anim(project_name: str) -> bool:
    pages = _expected_filmstrip_pages(project_name)
    if not pages:
        return False
    videos_dir = _wave_dir(project_subdir(get_project_dir(project_name), "filmstrip_videos"))
    if not videos_dir.is_dir():
        return False
    videos = [f for f in videos_dir.iterdir() if f.suffix.lower() in (".mp4", ".mov")]
    return len(videos) >= len(pages)


def _artifact_screenshots(project_name: str) -> bool:
    database_dir = project_subdir(get_project_dir(project_name), "database")
    links_csv = database_dir / f"os_doc_{project_name}_other_links.csv"
    if not links_csv.is_file():
        return True   # обычных ссылок не было — делать нечего

    expected = set()
    with open(links_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            src = (row.get("source_address") or "").strip()
            if src and not src.startswith("upd_"):
                expected.add(src)
    if not expected:
        return True

    articles = _wave_dir(project_subdir(get_project_dir(project_name), "articles"))
    if not articles.is_dir():
        return False
    done = {f.stem for f in articles.iterdir() if f.suffix.lower() in (".mov", ".mp4")}
    return expected.issubset(done)


# Шаг считается выполненным, только если и в маркере «done», и результат
# действительно лежит на диске — файлы могли удалить руками, а мог появиться
# и новый материал, под который шаг нужно прогнать заново.
STEP_ARTIFACT_CHECKS = {
    "stage_structure": _artifact_structure,
    "stage_parse_links": _artifact_parse_links,
    "stage_transcribe": _artifact_transcribe,
    "stage_xml": _artifact_xml,
    "stage_enrich": _artifact_enrich,
    "photo_filmstrip": _artifact_filmstrip,
    "photo_filmstrip_anim": _artifact_filmstrip_anim,
    "screenshots": _artifact_screenshots,
}


def effective_step_status(project_name: str, state: dict, step_id: str) -> str:
    """Статус шага с поправкой на диск: маркер может отставать от реальности
    (файлы удалили руками) или опережать её (проект собран до появления
    маркера). Ошибка и прерывание остаются как есть — их нужно видеть."""
    status = (state.get("steps") or {}).get(step_id, {}).get("status") or "pending"
    if status in ("failed", "interrupted"):
        return status

    check = STEP_ARTIFACT_CHECKS.get(step_id)
    if check is None:
        return status
    try:
        has_artifact = check(project_name)
    except OSError:
        has_artifact = False

    if has_artifact:
        return "done"
    return "pending" if status == "done" else status


def stage_status(state: dict, stage_number: int) -> str:
    ids = stage_step_ids(stage_number)
    steps = state.get("steps") or {}
    statuses = [steps.get(step_id, {}).get("status") for step_id in ids]
    if statuses and all(status == "done" for status in statuses):
        return "done"
    if any(status in ("done", "running", "failed", "interrupted") for status in statuses):
        return "partial"
    return "pending"


_STEP_STATUS_MARK_STYLE = {
    "done": ("✓", "ok"),
    "running": ("→", "accent"),
    "interrupted": ("→", "accent"),
    "failed": ("✗", "err"),
}


def _print_stage_checklist(project_name: str, state: dict, stage_number: int, step_ids: list):
    from progress_ui import console as rich_console
    from rich.table import Table
    from rich.text import Text
    from rich import box

    steps = state.get("steps") or {}
    table = Table(box=box.SIMPLE_HEAVY, show_header=False, pad_edge=False)
    table.add_column("mark", width=3)
    table.add_column("title")
    table.add_column("note", justify="right")
    for step_id in step_ids:
        status = steps.get(step_id, {}).get("status")
        mark, style = _STEP_STATUS_MARK_STYLE.get(status, ("·", "muted"))
        note = {"done": "готово", "running": "выполняется…", "interrupted": "прервано",
                "failed": "ошибка"}.get(status, "ожидает")
        title = FLOW_STEP_MAP[step_id]["title"]
        table.add_row(Text(mark, style=style), Text(title, style=("white" if status else "muted")), Text(note, style=style))

    stage_title = STAGE_MAP[stage_number]["title"]
    rich_console.print(
        f"[muted]Проект «{project_name}»[/]   [title]Стадия {stage_number} — {stage_title}[/]"
    )
    rich_console.print(table)


def run_pipeline_for_project(project_name: str, image_mode: str):
    """Общий движок для нового и для продолжаемого проекта: показывает 3
    стадии (с отметкой прогресса), даёт выбрать любую, после успешного
    завершения стадии сразу предлагает продолжить следующей — без
    необходимости заново открывать меню стадий."""
    stage_to_run = None

    while True:
        if stage_to_run is None:
            state = init_project_state(project_name)
            options = []
            for stage in STAGES:
                mark = _STAGE_STATUS_MARK.get(stage_status(state, stage["number"]), " ")
                options.append((f"[{mark}] Стадия {stage['number']} — {stage['title']}", stage["number"]))
            options.append(("Выход", "exit"))
            choice = select_option(f"Проект: {project_name}", options)
            if choice == "exit":
                return
            stage_to_run = choice

        step_ids = stage_step_ids(stage_to_run)
        state = init_project_state(project_name)
        _print_stage_checklist(project_name, state, stage_to_run, step_ids)

        # Стадии 1 и 3 переиспользуемы: их шаги можно доделывать по одному,
        # поэтому уже выполненные не предлагаются заново. В стадии 2 каждый
        # запуск добирает новый материал, там выбор шагов не нужен.
        if stage_to_run in (1, 3):
            marks = {"done": "✓", "skipped": "⏭", "failed": "✗", "interrupted": "→"}
            options = []
            preselected = []
            for step_id in step_ids:
                status = effective_step_status(project_name, state, step_id)
                options.append((f"[{marks.get(status, ' ')}] {FLOW_STEP_MAP[step_id]['title']}", step_id))
                if status != "done":
                    preselected.append(step_id)

            if not preselected:
                print("\nВсё в этой стадии уже сделано.")
            step_ids = select_many("Какие шаги выполнить? (пробел — отметить, Enter — запустить)",
                                   options, preselected)
            if not step_ids:
                print("Ничего не выбрано.")
                stage_to_run = None
                continue

        try:
            execute_flow_steps(project_name, image_mode, "new_project", step_ids)
        except KeyboardInterrupt:
            print(f"\n\033[33m⏸️  Остановлено на стадии {stage_to_run}. Прогресс сохранён — "
                  f"продолжить можно через «Продолжить работу над проектом».\033[0m")
            return
        except Exception as exc:
            print(f"\n❌ Ошибка на стадии {stage_to_run}: {exc}")
            stage_to_run = None
            continue

        if stage_to_run >= len(STAGES):
            print("\n\033[32m=== Все стадии проекта завершены ===\033[0m")
            stage_to_run = None
            continue

        next_stage = stage_to_run + 1
        next_title = STAGE_MAP[next_stage]["title"]
        if ask_confirm(f"Стадия {stage_to_run} завершена. Продолжить стадией {next_stage} — «{next_title}»?"):
            stage_to_run = next_stage
        else:
            stage_to_run = None


def run_new_project():
    """Новый проект: только имя, без списка прошлых проектов. Дальше —
    выбор и запуск стадий через общий движок."""
    project_name = ask_new_project_name()
    ask_project_location(project_name)
    image_mode = select_image_processing_mode()
    print(f"\n=== Новый проект: {project_name} ===")
    run_pipeline_for_project(project_name, image_mode)


def run_continue_project():
    """Продолжить работу над проектом: список существующих проектов,
    дальше — тот же движок стадий (скрипт сам знает, что уже сделано)."""
    projects = find_all_projects()
    if not projects:
        print("Нет существующих проектов. Используйте «Новый проект».")
        return

    choice = select_option("Продолжить работу над проектом", project_menu_options(projects))
    project_name = activate_project_path(choice)
    image_mode = select_image_processing_mode()
    run_pipeline_for_project(project_name, image_mode)


def run_selected_task_menu():
    project_name = None
    image_mode = None

    while True:
        try:
            options = [
                ("Назад", "back"),
                (CORE_PIPELINE_TITLE, "core"),
            ]
            options.extend(
                (f"{task['script']} — {task['title']}", idx)
                for idx, task in enumerate(SCRIPT_TASKS)
            )
            choice = select_option("Скрипты по очереди", options)
            if choice == "back":
                return

            if choice == "core":
                project_name = project_name or select_project_name()
                execute_flow_steps(project_name, image_mode or "crop", "new_project", [
                    "stage_structure",
                    "stage_parse_links",
                    "stage_transcribe",
                    "stage_xml",
                    "stage_enrich",
                    "stage_author",
                    "stage_images",
                ])
                continue

            task = SCRIPT_TASKS[choice]
            if task.get("needs_project") or task.get("project_arg"):
                project_name = project_name or select_project_name()
            if task.get("needs_image_mode"):
                image_mode = image_mode or select_image_processing_mode()
            run_script_task(task, project_name=project_name, image_mode=image_mode)
        except KeyboardInterrupt:
            print("\nОперация отменена пользователем.")
        except Exception as exc:
            print(f"\n❌ Ошибка: {exc}")


def run_direct_video_download():
    """Режим 2: скачать видео по ссылкам + сразу сделать плашки с источником.

    На каждое видео создаётся отдельная папка video_direct/{название видео}/
    Туда кладётся само видео и PNG-плашка источника рядом.
    """
    ensure_core_dependencies()
    project_name = (os.getenv("PROJECT_NAME") or "").strip() or select_project_name()

    # Non-interactive mode: read URLs from env var (set by web UI)
    env_urls = os.getenv("VIDEO_URLS", "").strip()
    urls: List[str] = []
    if env_urls:
        for line in env_urls.splitlines():
            line = line.strip()
            if line.startswith("http"):
                urls.append(line)
    else:
        print("\nВведите ссылки на видео (по одной, пустая строка — начать скачивание):")
        while True:
            url = ask_text("  URL").strip()
            if not url:
                if urls:
                    break
                continue
            # Поддержка вставки нескольких ссылок через пробел/запятую
            for part in re.split(r'[\s,]+', url):
                part = part.strip()
                if part.startswith('http'):
                    urls.append(part)

    if not urls:
        print("Ссылки не указаны.")
        return

    # Фильтр шортсов и очистка list= из URL
    shorts = [u for u in urls if is_shorts_url(u)]
    urls = [clean_url(u) for u in urls if not is_shorts_url(u)]
    if shorts:
        print(f"⏭️  Шортсы пропущены ({len(shorts)}): " + ", ".join(u[:60] for u in shorts))
    if not urls:
        print("Нет видео для скачивания (все — шортсы).")
        return

    project_dir = Path(DATA_DIR) / project_name
    video_direct_root = project_subdir(project_dir, "video_direct")
    video_direct_root.mkdir(parents=True, exist_ok=True)

    print("\n📁 Корень: video_direct/ (отдельная папка на каждое видео)")
    print(f"📊 Видео к скачиванию: {len(urls)}")

    # Получаем метаданные каналов заранее (для плашек и названий папок)
    req_session = requests.Session()
    logger = Logger()
    print("\n🔍 Получаю информацию о каналах...")
    url_meta: Dict[str, tuple] = {}
    for url in urls:
        channel, title = get_channel_and_title_for_url(req_session, url, logger)
        url_meta[url] = (channel, title)
        label = (title or url)[:60]
        print(f"  {label} → {channel or '?'}")

    cookies_file = get_cookies_file()

    def _unique_video_dir(base_name: str) -> Path:
        """Папка под видео по его названию; при совпадении добавляет суффикс."""
        candidate = video_direct_root / base_name
        suffix = 2
        while candidate.exists():
            candidate = video_direct_root / f"{base_name} ({suffix})"
            suffix += 1
        return candidate

    print("\n=== Скачивание ===")
    from progress_ui import StatusBoard
    ok = fail = 0
    pause_seconds = get_video_download_pause_seconds()
    total = len(urls)
    board = StatusBoard(3)
    for idx, url in enumerate(urls, 1):
        channel, title = url_meta[url]
        label = (title or url)[:60]

        # Папка называется по названию видео, а не по дате скачивания.
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip() if title else ""
        safe_title = safe_title.strip(". ")[:120] or f"video_{idx:02d}"
        video_dir = _unique_video_dir(safe_title)
        video_dir.mkdir(parents=True, exist_ok=True)

        if _download_video_direct(url, video_dir, cookies_file, board=board, idx=idx, total=total, initial_label=label):
            ok += 1
            author_path = video_dir / f"{safe_title}_author.png"
            try:
                _make_author_png(channel, author_path)
                board.log(f"  ✅ Скачано → {video_dir.name}/ | плашка: {author_path.name}")
            except Exception as e:
                board.log(f"  ✅ Скачано → {video_dir.name}/ | ❌ плашка не создана: {e}")
        else:
            fail += 1
            board.log(f"  ❌ Ошибка скачивания: {label}")
            from error_log import log_download_error
            log_download_error(project_name, "direct_video", safe_title, url)
            # Пустую папку убираем, чтобы не плодить мусор после неудачи.
            try:
                next(video_dir.iterdir())
            except StopIteration:
                video_dir.rmdir()
            except OSError:
                pass

        if idx < len(urls) and pause_seconds > 0:
            board.log(f"  ⏳ Пауза перед следующим видео: {pause_seconds:.1f} сек")
            time.sleep(pause_seconds)

    board.close()
    print(f"\n{'='*50}")
    print(f"Скачано: {ok}, ошибок: {fail}")
    print(f"📁 {video_direct_root}")


def run_gazety_generation():
    """Режим 3: сгенерировать газеты (статьи на рваной бумаге, та же механика,
    что и в стадии 3 — website_animate.py) по вставленным ссылкам — массово,
    без привязки к строкам таблицы проекта, как в «Скачать видео по ссылкам»."""
    ensure_core_dependencies()
    project_name = (os.getenv("PROJECT_NAME") or "").strip() or select_project_name()

    env_urls = os.getenv("GAZETY_URLS", "").strip()
    urls: List[str] = []
    if env_urls:
        for line in env_urls.splitlines():
            line = line.strip()
            if line.startswith("http"):
                urls.append(line)
    else:
        print("\nВведите ссылки на статьи (по одной, пустая строка — начать генерацию):")
        while True:
            url = ask_text("  URL").strip()
            if not url:
                if urls:
                    break
                continue
            # Поддержка вставки нескольких ссылок через пробел/запятую
            for part in re.split(r'[\s,]+', url):
                part = part.strip()
                if part.startswith('http'):
                    urls.append(part)

    if not urls:
        print("Ссылки не указаны.")
        return

    import hashlib
    import json
    import website_animate
    from error_log import log_download_error
    from progress_ui import render_bar, StatusBoard

    project_dir = Path(DATA_DIR) / project_name
    gazety_root = project_subdir(project_dir, "gazety_direct")
    gazety_root.mkdir(parents=True, exist_ok=True)

    print("\n📁 Корень: gazety_direct/ (отдельная папка на каждую статью)")
    print(f"📊 Статей к генерации: {len(urls)}")

    def _slug_for(url: str) -> str:
        return "gazeta-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

    def _unique_dir(base_name: str) -> Path:
        candidate = gazety_root / base_name
        suffix = 2
        while candidate.exists():
            candidate = gazety_root / f"{base_name} ({suffix})"
            suffix += 1
        return candidate

    total = len(urls)
    board = StatusBoard(2)
    ok = fail = 0

    for idx, url in enumerate(urls, 1):
        overall = (idx - 1) / total
        board.render([
            f"[{idx}/{total}] {url[:70]}",
            f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {ok}, ошибок: {fail})",
        ])

        slug = _slug_for(url)
        try:
            success, reason = website_animate.extract_article(url, slug)
            if not success:
                raise RuntimeError(f"извлечение текста: {reason}")

            headline = slug
            content_path = website_animate._PAPER_DIR / "renders" / slug / "source" / "content.json"
            try:
                content = json.loads(content_path.read_text(encoding="utf-8"))
                headline = content.get("headline") or slug
            except (OSError, ValueError):
                pass

            success, reason = website_animate.compose_article(slug)
            if not success:
                raise RuntimeError(f"компоновка: {reason}")

            safe_title = re.sub(r'[<>:"/\\|?*]', '_', headline).strip()[:120] or slug
            out_dir = _unique_dir(safe_title)
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"{safe_title}.mov"

            success, reason = website_animate.render_article(slug, output_path)
            if not success:
                raise RuntimeError(f"рендер: {reason}")

            ok += 1
            board.log(f"  ✅ {headline} → {out_dir.name}/")
        except Exception as exc:
            fail += 1
            board.log(f"  ❌ {url[:60]}: {exc}")
            log_download_error(project_name, "gazety_direct", url[:60], url, reason=str(exc))

    board.render([
        "готово",
        f"Всего:  [{render_bar(1.0)}] 100.0%  (готово: {ok}, ошибок: {fail})",
    ])
    board.close()

    print(f"\nСгенерировано: {ok}, ошибок: {fail}")
    print(f"📁 {gazety_root}")


def _current_setting_display(field: dict) -> str:
    value = os.getenv(field["key"], "").strip()
    if not value:
        return "по умолчанию" if field["default"] is None else str(field["default"])
    if field["kind"] == "choice":
        for key, label in field["choices"]:
            if key == value:
                return label
    return value


def run_scan_folders_menu():
    """Папки, в которых искать проекты помимо стандартного корня."""
    while True:
        folders = load_scan_folders(__file__)
        print(f"\nСтандартная папка: {DEFAULT_DATA_DIR}")
        if folders:
            print("Дополнительные папки:")
            for folder in folders:
                mark = "" if Path(folder).is_dir() else "  (недоступна)"
                print(f"  • {folder}{mark}")
        else:
            print("Дополнительных папок нет.")

        options = [("Добавить папку", "add")]
        if folders:
            options.append(("Убрать папку", "remove"))
        options.append(("Назад", "back"))
        choice = select_option("Папки, где искать проекты", options)

        if choice == "back":
            return
        if choice == "add":
            answer = ask_text("Путь к папке: ")
            if not answer:
                continue
            folder = Path(answer).expanduser().resolve()
            if not folder.is_dir():
                print(f"Папка не найдена: {folder}")
                continue
            add_scan_folder(folder, __file__)
            print(f"✓ Добавлено: {folder}")
        elif choice == "remove":
            target = select_option("Какую папку убрать?", [(f, f) for f in folders] + [("Отмена", "")])
            if target:
                remove_scan_folder(target, __file__)
                print(f"✓ Убрано: {target}")


def run_settings_menu():
    while True:
        options = [
            (f"{field['label']}: {_current_setting_display(field)}", field["key"])
            for field in SETTINGS_FIELDS
        ]
        folders_count = len(load_scan_folders(__file__))
        options.append((f"Папки, где искать проекты: {folders_count} доп.", "__scan_folders__"))
        options.append(("Назад", "back"))
        choice = select_option("Настройки", options)
        if choice == "back":
            return
        if choice == "__scan_folders__":
            run_scan_folders_menu()
            continue

        field = SETTINGS_FIELD_MAP[choice]
        if field["kind"] == "choice":
            value_options = [(label, key) for key, label in field["choices"]] + [("— сбросить на умолчание —", "")]
            new_value = select_option(field["label"], value_options)
        else:
            current = os.getenv(field["key"], "").strip()
            print(f"\n{field['label']}")
            print(f"Текущее: {current or '(по умолчанию)'}")
            new_value = clean_path_value(ask_text("Новый путь (пусто — сбросить на умолчание): "))
            if new_value and not Path(new_value).expanduser().is_dir():
                print(f"⚠️  Папки нет: {new_value}")
                if not ask_confirm("Всё равно сохранить?", default=False):
                    continue

        set_setting(field["key"], new_value, __file__)
        if new_value:
            print(f"✓ Сохранено: {field['label']} = {new_value}")
        else:
            print(f"✓ Сброшено на умолчание: {field['label']}")
        if field.get("restart_required"):
            print("  Изменение применится после перезапуска программы.")


UPDATE_CACHE_FILE = BASE_DIR / ".update_check_cache.json"
UPDATE_CHECK_INTERVAL_SECONDS = 3600


def _git(args, timeout=8):
    return subprocess.run(
        ["git", "-C", str(BASE_DIR), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _resolve_remote_branch():
    remote = _git(["remote"]).stdout.strip().splitlines()
    remote = remote[0] if remote else "origin"
    symref = _git(["ls-remote", "--symref", remote, "HEAD"])
    m = re.search(r"refs/heads/(\S+)", symref.stdout)
    remote_branch = m.group(1) if m else "main"
    return remote, remote_branch


def check_for_updates(force: bool = False) -> dict:
    """git fetch + сравнение HEAD с origin/main. Кэшируется на час — чтобы
    не дёргать GitHub при каждом заходе в меню. Любая сетевая/git ошибка
    (нет сети, нет remote) тихо даёт available=False, а не падает."""
    now = time.time()
    if not force and UPDATE_CACHE_FILE.exists():
        try:
            cached = json.loads(UPDATE_CACHE_FILE.read_text(encoding="utf-8"))
            if now - cached.get("checked_at", 0) < UPDATE_CHECK_INTERVAL_SECONDS:
                return cached
        except Exception:
            pass

    result = {"available": False, "ahead_by": 0, "checked_at": now, "error": None}
    try:
        remote, remote_branch = _resolve_remote_branch()
        fetch = _git(["fetch", "--quiet", remote, remote_branch], timeout=10)
        if fetch.returncode != 0:
            result["error"] = (fetch.stderr or "fetch failed").strip()[:200]
        else:
            count = _git(["rev-list", "--count", f"HEAD..{remote}/{remote_branch}"])
            ahead = int(count.stdout.strip() or "0")
            result["ahead_by"] = ahead
            result["available"] = ahead > 0
    except Exception as exc:
        result["error"] = str(exc)[:200]

    try:
        UPDATE_CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return result


def install_update():
    print("\n=== Проверка и установка обновления ===")
    status = check_for_updates(force=True)
    if status.get("error"):
        print(f"❌ Не удалось проверить обновления: {status['error']}")
        return
    if not status["available"]:
        print("✓ Уже установлена последняя версия.")
        return
    print(f"Доступно обновление: {status['ahead_by']} новых коммитов. Устанавливаю...")
    remote, remote_branch = _resolve_remote_branch()
    if run_command(["git", "-C", str(BASE_DIR), "pull", remote, remote_branch], title="git pull", continue_on_error=True):
        print("✓ Обновление установлено. Перезапустите программу, чтобы применить изменения.")
        check_for_updates(force=True)
    else:
        print("❌ Не удалось установить обновление автоматически — проверьте git-статус вручную.")


def _errors_menu_core_handlers() -> dict:
    """Ретраи, чья логика живёт в core/main.py (не в scripts/) — передаются
    в errors_menu явно, чтобы не тянуть обратную зависимость scripts/ →
    core/main.py."""

    def retry_stage_images(project_name: str, row: dict):
        project_dir = Path(DATA_DIR) / project_name
        upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
        base_images_dir = str(project_subdir(project_dir, 'images'))
        pictures_dir = os.path.join(base_images_dir, upd_subdir) if upd_subdir else base_images_dir
        os.makedirs(pictures_dir, exist_ok=True)
        ok = download_one(row["url"], row["display_name"], pictures_dir)
        return (True, "") if ok else (False, "повтор скачивания не удался")

    def retry_direct_video(project_name: str, row: dict):
        project_dir = Path(DATA_DIR) / project_name
        video_dir = project_subdir(project_dir, "video_direct")
        cookies_file = get_cookies_file()
        ok = _download_video_direct(row["url"], video_dir, cookies_file)
        return (True, "") if ok else (False, "повтор скачивания не удался")

    def retry_stage_author(project_name: str, row: dict):
        project_dir = Path(DATA_DIR) / project_name
        author_dir = project_subdir(project_dir, "author")
        author_dir.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        logger = Logger()
        channel, title = get_channel_and_title_for_url(session, row["url"], logger)
        if not channel:
            return False, "канал не определился по ссылке"
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip() if title else ""
        name = f"{row['display_name']} {safe_title}_author.png" if safe_title else f"{row['display_name']}_author.png"
        _make_author_png(channel, author_dir / name)
        return True, ""

    return {
        "stage_images": retry_stage_images,
        "direct_video": retry_direct_video,
        "stage_author": retry_stage_author,
    }


def run_errors_menu_entry():
    from errors_menu import run_errors_menu
    run_errors_menu(select_project_name, select_option, ask_confirm, _errors_menu_core_handlers())


def main_menu():
    from progress_ui import console as rich_console
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    rich_console.print(Panel(
        Text.from_markup(
            "[brand]OSNOVATELI.DOC FRAMEWORK[/]\n[muted]терминальный пайплайн монтажа документалок[/]",
            justify="center",
        ),
        box=box.ROUNDED, border_style="accent", padding=(1, 2),
    ))

    while True:
        try:
            update_status = check_for_updates()
            if update_status.get("available"):
                rich_console.print(
                    f"[warn]Доступно обновление[/] [muted]— {update_status['ahead_by']} "
                    f"новых коммитов на GitHub[/]"
                )

            reset_active_projects_root()
            choice = select_option(
                "Главное меню",
                [
                    ("1. Новый проект", "new_project"),
                    ("2. Продолжить работу над проектом", "continue_project"),
                    ("3. Скачать видео по ссылкам", "direct_video"),
                    ("4. Сгенерировать газеты по ссылкам", "gazety_direct"),
                    ("5. Скрипты по очереди", "scripts"),
                    ("6. Ошибки проекта", "errors"),
                    ("7. Настройки", "settings"),
                    ("8. Установить ВСЕ зависимости", "install"),
                    ("9. Проверить и установить обновление", "update"),
                    ("0. Выход", "exit"),
                ],
            )
            if choice == "new_project":
                run_new_project()
            elif choice == "continue_project":
                run_continue_project()
            elif choice == "direct_video":
                run_direct_video_download()
            elif choice == "gazety_direct":
                run_gazety_generation()
            elif choice == "scripts":
                run_selected_task_menu()
            elif choice == "errors":
                run_errors_menu_entry()
            elif choice == "settings":
                run_settings_menu()
            elif choice == "install":
                install_all_dependencies()
            elif choice == "update":
                install_update()
            elif choice == "exit":
                return
        except KeyboardInterrupt:
            print("\nОперация отменена пользователем.")
        except Exception as exc:
            print(f"\n❌ Ошибка: {exc}")


def python_can_install_packages(executable):
    try:
        return subprocess.run(
            [str(executable), "-c", "import pyexpat, pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


def find_preferred_python():
    candidates = []
    if os.name == "nt":
        py_launcher = shutil.which("py")
        if py_launcher:
            for version in ("-3.13", "-3.12", "-3.11", "-3.10"):
                candidates.append([py_launcher, version])
        python_exe = shutil.which("python")
        if python_exe:
            candidates.append([python_exe])
    else:
        for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
            path = shutil.which(name)
            if path:
                candidates.append([path])

    for candidate in candidates:
        if subprocess.run(
            candidate + ["-c", "import pyexpat, pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return candidate
    return None


def restart_with_preferred_python_if_needed():
    if os.getenv("OS_DOC_PYTHON_REEXEC") == "1":
        return

    current_is_unstable = sys.version_info >= (3, 14)
    current_is_broken = not python_can_install_packages(sys.executable)
    if not current_is_unstable and not current_is_broken:
        return

    preferred = find_preferred_python()
    if not preferred:
        return

    if len(preferred) == 1 and Path(preferred[0]).resolve() == Path(sys.executable).resolve():
        return

    env = os.environ.copy()
    env["OS_DOC_PYTHON_REEXEC"] = "1"
    print("Текущий Python не подходит для установки зависимостей.")
    print("Перезапускаю через: " + " ".join(preferred))
    os.execve(preferred[0], preferred + [str(Path(__file__).resolve())], env)


if __name__ == "__main__":
    restart_with_preferred_python_if_needed()
    main_menu()
