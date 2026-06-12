import os
import re
import csv
import sys
import json
import time
import shutil
import platform
import importlib
import subprocess
import traceback
import textwrap
import urllib.parse
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
except ImportError:
    questionary = None
    Choice = None


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


class Logger:
    def __init__(self):
        self.error_count = 0
        self.success_count = 0
        self.cache_hits = 0
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
    def error(self, msg): self.error_count += 1; self._write("ERROR", msg)
    def warning(self, msg): self._write("WARN", msg)
    def success(self, msg): self.success_count += 1; self._write("SUCCESS", msg)


DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(os.getenv("BASE_DIR", str(DEFAULT_BASE_DIR))).resolve()
DATA_DIR = str(BASE_DIR / 'data')
STRUCTURE_FILE = str(BASE_DIR / 'default_project_structure.txt')
ENV_FILE = str(BASE_DIR / '.env')
SCRIPTS_DIR = BASE_DIR / 'scripts'
REQUIREMENTS_FILE = BASE_DIR / 'requirements.txt'


# Project structure creation function
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

    def get_project_name():
        return resolve_project_name()

    def get_required_structure():
        try:
            with open(STRUCTURE_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f'Ошибка: файл {STRUCTURE_FILE} не найден')
            return None
        return [l.strip() for l in lines if l.strip() and not l.startswith('#')]

    def check_existing_structure(project_dir):
        if not os.path.exists(project_dir):
            return [], []
        existing = []
        with_files = []
        for item in os.listdir(project_dir):
            item_path = os.path.join(project_dir, item)
            if os.path.isdir(item_path):
                existing.append(item)
                try:
                    if any(os.path.isfile(os.path.join(item_path, f)) for f in os.listdir(item_path)):
                        with_files.append(item)
                except PermissionError:
                    print(f'Нет доступа к папке: {item}')
        return existing, with_files

    print("=== OSNOVATELI.DOC FRAMEWORK ===")
    print(f"\n\033[32m=== Stage1. Start! Создание структуры проекта ===\033[0m")

    project_name = get_project_name()
    project_dir = os.path.join(DATA_DIR, project_name)

    required_folders = get_required_structure()
    if required_folders is None:
        print(f'Не удалось создать структуру проекта {project_name}')
        return None

    existing_folders, folders_with_files = check_existing_structure(project_dir)

    if not os.path.exists(project_dir):
        os.makedirs(project_dir, exist_ok=True)
        print(f'Создана директория проекта: {project_dir}')
        existing_folders = []
        folders_with_files = []
    else:
        print(f'Проект уже существует: {project_dir}')

    missing_folders = [f for f in required_folders if f not in existing_folders]

    for folder_name in missing_folders:
        os.makedirs(os.path.join(project_dir, folder_name), exist_ok=True)

    print(f'\n\033[32m=== Stage1. Done! Создана структура проекта ===\033[0m')
    return project_name


# Link parsing function
def parse_links(project_name):
    load_dotenv(ENV_FILE, override=True)

    project_dir = os.path.join(DATA_DIR, project_name)
    database_dir = os.path.join(project_dir, 'database')
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
            raise RuntimeError("Заполните .env и запустите Stage2 повторно.")

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
        raise gspread.exceptions.WorksheetNotFound("Не удалось определить рабочий лист.")

    def extract_spreadsheet_id_from_url():
        while True:
            url = input("Введите ссылку на Google таблицу: ").strip()
            if not url:
                print("Ошибка: ссылка не может быть пустой.")
                continue
            match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
            if match:
                return url, match.group(1)
            print("Ошибка: не удалось извлечь SPREADSHEET_ID из ссылки.")

    def save_table_to_csv(spreadsheet_id, is_reparse, service_account_info):
        scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = resolve_worksheet(sh)
        all_values = worksheet.get_all_values()

        if is_reparse:
            timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
            filename = f'input_gdoc_{timestamp}.csv'
        else:
            filename = 'input_gdoc.csv'

        filepath = os.path.join(database_dir, filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(all_values)

        print(f"Структура таблицы сохранена в: {filename} ({len(all_values)} строк)")
        return all_values, filename

    def extract_links_from_column_b(gdoc_filename):
        filepath = os.path.join(database_dir, gdoc_filename)
        all_links = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for row_num, row in enumerate(csv.reader(f), 1):
                if len(row) > 1 and row[1].strip():
                    for idx, url in enumerate(re.findall(r'https?://[^\s,;"\'<>]+', row[1].strip()), 1):
                        all_links.append({
                            'source_address': f"B{row_num}_{idx}",
                            'url': url,
                        })
        print(f"Найдено {len(all_links)} ссылок в колонке B")
        return all_links

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
        if is_youtube_url(url):
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

    print(f"\n\033[32m=== Stage2. Start! Парсинг ссылок из Google таблицы ===\033[0m")
    service_account_info = get_service_account_info()
    service_email = service_account_info["client_email"]
    print(f"\n\033[33mДайте данному email доступ 'Читатель' к таблице:\n{service_email}\033[0m\n")
    print(f"Проект: {project_name}")

    spreadsheet_url, spreadsheet_id = extract_spreadsheet_id_from_url()
    is_reparse = check_if_reparse(spreadsheet_url)

    if is_reparse:
        print("ВНИМАНИЕ: Повторный парсинг. Новые данные будут добавлены после строк upd_<дата>")
    else:
        print("Первый парсинг этой ссылки")

    save_input_link_info(spreadsheet_url, spreadsheet_id, is_reparse)
    all_values, gdoc_filename = save_table_to_csv(spreadsheet_id, is_reparse, service_account_info)
    all_links = extract_links_from_column_b(gdoc_filename)
    save_links_to_csv(all_links, is_reparse)
    categorized = categorize_and_save(all_links, is_reparse)

    print(f"\n\033[32m=== Stage2. Done! Ссылки успешно извлечены ===\033[0m")


# Channel enrichment function
def enrich_channels(project_name: str):
    database_dir = os.path.join(DATA_DIR, project_name, 'database')

    def sanitize_channel_name(channel: str) -> str:
        channel = (channel or "").strip()
        if not channel or FORBIDDEN_SOURCE_URL in channel:
            return ""
        return channel

    def fetch_json(session, url):
        try:
            response = session.get(url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT)
            if response.status_code >= 400:
                return None
            return response.json()
        except Exception:
            return None

    def get_channel_and_title_for_url(session, url, logger):
        """Возвращает (channel, title) из YouTube oEmbed."""
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
            payload = fetch_json(session, oembed_url)
            if payload and payload.get("author_name"):
                channel = sanitize_channel_name(str(payload["author_name"]))
                title = (payload.get("title") or "").strip()
                logger.stats["youtube"]["success"] += 1
                if channel:
                    logger.success(f"{url} -> {channel}")
                return channel, title
            logger.stats["youtube"]["error"] += 1
        except Exception:
            pass
        return "", ""

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
        print(f"Файл youtube_links.csv не найден, обогащение каналов пропущено.")
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

    print(f"\n\033[32m=== Stage4. Start! Получение названий YouTube-каналов ===\033[0m")

    cache_file = os.path.join(database_dir, 'channel_cache.csv')
    cache = load_cache(cache_file)
    logger = Logger()
    session = requests.Session()
    results: List[Tuple[str, str, str, str]] = []  # (source_address, url, channel, title)

    for idx, (source_address, url) in enumerate(links, 1):
        if url in cache:
            logger.cache_hits += 1
            channel, title = cache[url]
            results.append((source_address, url, channel, title))
            continue
        channel, title = get_channel_and_title_for_url(session, url, logger)
        cache[url] = (channel, title)
        results.append((source_address, url, channel, title))
        time.sleep(0.12)

    save_cache(cache, cache_file)

    output_file = os.path.join(database_dir, f'os_doc_{project_name}_channels.csv')
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['source_address', 'url', 'channel', 'title'])
        for row in results:
            writer.writerow(row)

    found = sum(1 for _, _, ch, _ in results if ch)
    print(f"Каналов найдено: {found}/{len(results)}")
    print(f"\n\033[32m=== Stage4. Done! Названия каналов записаны ===\033[0m")


# XML placeholders creation function
def create_xml_placeholders(project_name: str):
    import textwrap

    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    PROJECT_FONT_PATH = os.path.join(BASE_DIR, 'assets', 'font', 'theater.bold-condensed.ttf')
    database_dir = os.path.join(DATA_DIR, project_name, 'database')
    base_placeholders_dir = os.path.join(DATA_DIR, project_name, 'placeholders_xml')
    placeholders_dir = os.path.join(base_placeholders_dir, upd_subdir) if upd_subdir else base_placeholders_dir

    print(f"\n\033[32m=== Stage3. Start! Создание XML-плейсхолдеров ===\033[0m")

    def get_latest_input_gdoc(db_dir):
        db_path = Path(db_dir)
        if not db_path.exists():
            return None
        files = sorted(str(path) for path in db_path.iterdir() if path.is_file() and path.name.startswith('input_gdoc') and path.suffix == '.csv')
        if not files:
            return None
        dated = [f for f in files if 'input_gdoc_' in os.path.basename(f)]
        if dated:
            return sorted(dated)[-1]
        base = os.path.join(db_dir, 'input_gdoc.csv')
        return base if os.path.exists(base) else None

    def remove_links(text):
        if not text:
            return text
        return ' '.join(re.sub(r'https?://[^\s]+', '', text).split())

    def calculate_font_size(texts):
        total = len(' '.join(texts).strip())
        if total <= 100: return 60
        if total <= 300: return 50
        if total <= 600: return 40
        if total <= 1000: return 35
        if total <= 1500: return 30
        if total <= 2500: return 25
        return 20

    def load_font(size):
        for path in [PROJECT_FONT_PATH, '/System/Library/Fonts/Arial.ttf', '/System/Library/Fonts/Helvetica.ttc']:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def get_existing(base_dir):
        existing = set()
        if not os.path.exists(base_dir):
            return existing
        for f in os.listdir(base_dir):
            if f.endswith('.jpg'):
                try:
                    existing.add(int(f.replace('.jpg', '')))
                except ValueError:
                    pass
            subpath = os.path.join(base_dir, f)
            if os.path.isdir(subpath):
                for fname in os.listdir(subpath):
                    if fname.endswith('.jpg'):
                        try:
                            existing.add(int(fname.replace('.jpg', '')))
                        except ValueError:
                            pass
        return existing

    def create_image(col_a, col_b, col_c, col_d, row_number, output_path):
        texts = [col_a, col_b, col_c, col_d]
        font_size = calculate_font_size(texts)
        image = Image.new('RGB', (1920, 1080), color='white')
        draw = ImageDraw.Draw(image)
        font = load_font(font_size)
        label_font = load_font(font_size + 10)
        index_font = load_font(font_size + 20)

        index_text = f"#{row_number}"
        bbox = draw.textbbox((0, 0), index_text, font=index_font)
        draw.text((1920 - 100 - (bbox[2] - bbox[0]), 100), index_text, fill=(50, 50, 50), font=index_font)

        chars_per_line = (1920 - 200) // (font_size // 2)
        current_y = 100 + font_size + 30
        line_spacing = font_size * 1.2

        for text, label in [(col_a, 'VOICEOVER'), (remove_links(col_b), 'STORYBOARD'), (col_c, 'MOGRT'), (col_d, 'COMMENT')]:
            if text and text.strip():
                draw.text((100, current_y), label, fill=(100, 100, 100), font=label_font)
                current_y += line_spacing * 1.5
                for line in textwrap.wrap(text.strip(), width=chars_per_line, break_long_words=False, break_on_hyphens=False):
                    draw.text((100, current_y), line, fill=(0, 0, 0), font=font)
                    current_y += line_spacing
                current_y += line_spacing * 0.8

        image.save(output_path, 'JPEG', quality=95)

    csv_file = get_latest_input_gdoc(database_dir)
    if not csv_file:
        print("Файл input_gdoc.csv не найден, Stage3 пропущен.")
        return

    rows_data = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            for i, row in enumerate(csv.reader(f), 1):
                cols = (row + ['', '', '', ''])[:4]
                if any(c.strip() for c in cols):
                    rows_data.append({'row_number': i, 'col_a': cols[0].strip(), 'col_b': cols[1].strip(), 'col_c': cols[2].strip(), 'col_d': cols[3].strip()})
    except Exception as e:
        print(f"Ошибка при чтении input_gdoc.csv: {e}")
        return

    if not rows_data:
        print("Данных для обработки не найдено.")
        return

    os.makedirs(placeholders_dir, exist_ok=True)
    existing = get_existing(base_placeholders_dir)
    created = 0
    skipped = 0

    for row in rows_data:
        n = row['row_number']
        if n in existing:
            skipped += 1
            continue
        output_path = os.path.join(placeholders_dir, f"{n}.jpg")
        try:
            create_image(row['col_a'], row['col_b'], row['col_c'], row['col_d'], n, output_path)
            created += 1
            print(f"[{n}] Создан плейсхолдер")
        except Exception as e:
            print(f"[{n}] Ошибка: {e}")

    print(f"Создано: {created}, пропущено: {skipped}")
    print(f"\n\033[32m=== Stage3. Done! XML-плейсхолдеры созданы ===\033[0m")


_GEOLOGICA_FONT_PATH = Path(BASE_DIR) / "assets" / "Design Preparation" / "FONT" / "Geologica" / "Geologica-VariableFont_CRSV,SHRP,slnt,wght.ttf"
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


def _download_video_direct(url: str, output_dir: Path, cookies_file: Optional[str] = None) -> bool:
    """Скачивает одно видео через pull-vids Docker в указанную папку."""
    pull_vids_dir = SCRIPTS_DIR / "pull-vids"
    if not pull_vids_dir.exists():
        print(f"  ❌ pull-vids не найден: {pull_vids_dir}")
        return False
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = ['docker', 'compose', 'run', '--rm', '-v', f'{output_dir}:/downloads']
    if cookies_file and Path(cookies_file).exists():
        cmd += ['-v', f'{cookies_file}:/cookies.txt', 'pull-vids', '--cookies', '/cookies.txt', '-o', '/downloads', url]
    else:
        cmd += ['pull-vids', '-o', '/downloads', url]
    result = subprocess.run(cmd, cwd=str(pull_vids_dir), stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                print(f"  {line}")
        return False
    return True


# Author image creation function
def create_author_images(project_name: str):

    def sanitize_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def make_output_name(source_address: str, title: str) -> str:
        if title:
            safe_title = sanitize_filename(title)
            return f"{source_address} {safe_title}_author.png"
        return f"{source_address}_author.png"

    print(f"\n\033[32m=== Stage5. Start! Создание изображений с источниками ===\033[0m")

    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    project_dir = Path(DATA_DIR) / project_name
    channels_csv = project_dir / "database" / f"os_doc_{project_name}_channels.csv"
    base_author_dir = project_dir / "author"
    author_dir = base_author_dir / upd_subdir if upd_subdir else base_author_dir

    if not channels_csv.exists():
        print(f"Файл channels.csv не найден, Stage5 пропущен.")
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

    created = 0
    skipped = 0
    for idx, (source_address, url, channel_name, title) in enumerate(data, 1):
        output_name = make_output_name(source_address, title)
        output_path = author_dir / output_name
        old_output_path = author_dir / f"{source_address}_author.png"

        # В режиме правок дополнительно проверяем базовую папку
        base_output_path = base_author_dir / output_name
        base_old_output_path = base_author_dir / f"{source_address}_author.png"
        already_exists = (
            output_path.exists()
            or (output_path != old_output_path and old_output_path.exists())
            or (upd_subdir and (base_output_path.exists() or base_old_output_path.exists()))
        )
        if already_exists:
            skipped += 1
            continue
        try:
            _make_author_png(channel_name, output_path)
            created += 1
            print(f"[{idx}/{len(data)}] {source_address} -> {output_path.name}")
        except Exception as e:
            print(f"[{idx}/{len(data)}] Ошибка: {source_address}: {e}")

    print(f"Создано: {created}, пропущено: {skipped}")
    print(f"\n\033[32m=== Stage5. Done! Изображения с источниками созданы ===\033[0m")


# Image download function (from scripts/2_download_img.py)
def download_images(project_name: str):
    from urllib.parse import urlparse, parse_qs, unquote

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

    def log_error(display_name, url, error_csv, pictures_dir):
        file_exists = os.path.exists(error_csv)
        with open(error_csv, 'a', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(['source_address', 'url'])
            w.writerow([display_name, url])
        error_placeholder(display_name, pictures_dir)

    print(f"\n\033[32m=== Stage6. Start! Скачивание изображений ===\033[0m")

    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    project_dir = os.path.join(DATA_DIR, project_name)
    database_dir = os.path.join(project_dir, 'database')
    base_images_dir = os.path.join(project_dir, 'images')
    pictures_dir = os.path.join(base_images_dir, upd_subdir) if upd_subdir else base_images_dir
    if upd_subdir:
        print(f"Волна правок: {upd_subdir}")
    csv_file = os.path.join(database_dir, f'os_doc_{project_name}_image_links.csv')
    error_csv = os.path.join(database_dir, f'os_doc_{project_name}_download_img_errors.csv')

    os.makedirs(pictures_dir, exist_ok=True)

    if not os.path.exists(csv_file):
        print(f"Файл image_links.csv не найден, Stage6 пропущен.")
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
        print(f"\n\033[32m=== Stage6. Done! Изображения скачаны ===\033[0m")
        return

    ok = 0
    fail = 0
    total = len(to_download)

    def _worker(item):
        time.sleep(0.5)  # небольшая пауза чтобы не бомбить сервер
        return item, download_one(item['url'], item['display_name'], pictures_dir)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_worker, L): L for L in to_download}
        done = 0
        for future in as_completed(futures):
            done += 1
            L, success = future.result()
            print(f"[{done}/{total}] {L['display_name']} — {'✓' if success else '✗'}")
            if success:
                ok += 1
            else:
                fail += 1
                log_error(L['display_name'], L['url'], error_csv, pictures_dir)

    print(f"Скачано: {ok}, ошибок: {fail}, пропущено (уже есть): {len(links) - len(to_download)}")
    if fail:
        print(f"Ошибки: {os.path.basename(error_csv)}")
    print(f"\n\033[32m=== Stage6. Done! Изображения скачаны ===\033[0m")


SCRIPT_TASKS = [
    {
        "title": "Проверить Krea API",
        "script": "check_krea_api.py",
        "needs_project": False,
        "only_in_all_mode": "nano",
    },
    {
        "title": "Обработать картинки: Nano Banana 2 или crop 16:9",
        "script": "2.1_smart_cropping.py",
        "needs_project": True,
        "needs_image_mode": True,
    },
    {
        "title": "Создать pulltube_links.txt из YouTube CSV",
        "script": "3.2_pulltube.py",
        "needs_project": True,
    },
    {
        "title": "Создать motionarray_links.txt из MotionArray CSV",
        "script": "3.3_motionarray.py",
        "needs_project": True,
    },
    {
        "title": "Скачать YouTube видео через pull-vids Docker",
        "script": "3.4_pullvids_download.py",
        "needs_project": True,
    },
    {
        "title": "Сконвертировать скачанные видео в MP4",
        "script": "3.5_pullvids_convert.py",
        "needs_project": True,
        "requires_convert_confirm": True,
    },
    {
        "title": "Переименовать YouTube видео",
        "script": "4_pulltube_rename.py",
        "needs_project": True,
        "project_arg": True,
    },
    {
        "title": "Переименовать MotionArray видео",
        "script": "4.1_motionarray_rename.py",
        "needs_project": True,
        "project_arg": True,
    },
    {
        "title": "Создать video placeholders из фото",
        "script": "5_photo_placeholders.py",
        "needs_project": True,
    },
    {
        "title": "Сделать скриншоты other links",
        "script": "7_screenshot_other_links.py",
        "needs_project": True,
        "project_arg": True,
    },
    {
        "title": "Разобрать ошибки скачивания",
        "script": "sort_errors.py",
        "needs_project": False,
    },
]


CORE_PIPELINE_TITLE = "Core pipeline: структура проекта, Google таблица, CSV, XML, авторы, картинки"


def run_command(cmd, cwd=None, env=None, continue_on_error=False):
    print(f"\n$ {' '.join(str(part) for part in cmd)}")
    result = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd or BASE_DIR),
        env=env,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        if result.stderr:
            tail = result.stderr.decode(errors="replace").strip().splitlines()
            for line in tail[-20:]:
                print(f"  {line}")
        message = f"Команда завершилась с ошибкой: {result.returncode}"
        if continue_on_error:
            print(f"⚠️  {message}. Продолжаю.")
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


def install_playwright_chromium():
    run_command([sys.executable, "-m", "playwright", "install", "chromium"])


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


def install_docker_desktop():
    print("\n=== Проверка Docker Desktop / Docker Compose ===")
    docker_ok = shutil.which("docker") is not None
    compose_ok = False

    if docker_ok:
        try:
            compose_ok = subprocess.run(
                ["docker", "compose", "version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
        except Exception:
            compose_ok = False

    if docker_ok and compose_ok:
        print("✓ Docker и Docker Compose уже доступны")
        return

    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        run_command(["brew", "install", "--cask", "docker"])
        if shutil.which("open"):
            run_command(["open", "-a", "Docker"], continue_on_error=True)
        print("Откройте Docker Desktop и дождитесь статуса Running перед скачиванием YouTube.")
        return

    if system == "windows" and shutil.which("winget"):
        run_command([
            "winget",
            "install",
            "--id",
            "Docker.DockerDesktop",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ])
        print("Запустите Docker Desktop перед скачиванием YouTube.")
        return

    print("⚠️  Docker Desktop не найден и не установлен автоматически.")
    print("Установите Docker Desktop вручную: https://www.docker.com/products/docker-desktop/")


def install_all_dependencies():
    print("\n\033[32m=== Установка всех зависимостей ===\033[0m")
    print(f"Python: {sys.executable}")
    print(f"Version: {platform.python_version()}")
    install_python_requirements()
    install_playwright_chromium()
    install_ffmpeg()
    install_docker_desktop()
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
        answer = questionary.text(message).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer.strip()
    return input(message).strip()


def ask_confirm(message):
    if can_use_interactive_menu():
        answer = questionary.confirm(message, default=True).ask()
        if answer is None:
            raise KeyboardInterrupt
        return bool(answer)
    answer = input(f"{message} (y/n): ").strip().lower()
    return answer in {"y", "yes", "д", "да"}


def list_existing_projects():
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        return []
    return sorted(path.name for path in data_path.iterdir() if path.is_dir())


def select_project_name():
    projects = list_existing_projects()
    if projects:
        create_value = "__create_new_project__"
        options = [(name, name) for name in projects]
        options.append(("Создать новый проект", create_value))
        choice = select_option("Выбор проекта", options)
        if choice != create_value:
            os.environ["PROJECT_NAME"] = choice
            print(f"Проект: {choice}")
            return choice

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
    mode = (os.getenv("IMAGE_PROCESSING_MODE") or "").strip().lower()
    if mode in {"nano", "crop"}:
        return mode

    mode = select_option(
        "Режим обработки картинок",
        [
            ("Nano Banana 2", "nano"),
            ("Crop 16:9", "crop"),
        ],
    )
    os.environ["IMAGE_PROCESSING_MODE"] = mode
    return mode


def build_script_env(project_name=None, image_mode=None):
    env = os.environ.copy()
    env["BASE_DIR"] = str(BASE_DIR)
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

    print(f"\n\033[36m=== Запуск: {task['script']} ===\033[0m")
    print(task["title"])
    return run_command(
        cmd,
        cwd=BASE_DIR,
        env=build_script_env(project_name=project_name, image_mode=image_mode),
        continue_on_error=task.get("continue_on_error", False),
    )


def run_core_pipeline(project_name):
    ensure_core_dependencies()
    os.environ["PROJECT_NAME"] = project_name
    created_project_name = create_structure()
    if not created_project_name:
        return
    parse_links(created_project_name)
    create_xml_placeholders(created_project_name)
    enrich_channels(created_project_name)
    create_author_images(created_project_name)
    download_images(created_project_name)


def tasks_for_all_run(image_mode, convert_videos=False):
    selected = []
    for task in SCRIPT_TASKS:
        if task.get("requires_convert_confirm") and not convert_videos:
            continue
        optional_mode = task.get("only_in_all_mode")
        if optional_mode and optional_mode != image_mode:
            continue
        selected.append(task)
    return selected


def run_new_project():
    """Flow 0: новый проект — создаёт структуру и запускает полный пайплайн."""
    ensure_core_dependencies()
    project_name = select_project_name()
    image_mode = select_image_processing_mode()
    convert_videos = ask_confirm("Конвертировать скачанные видео в MP4 после загрузки?")

    print("\n=== 0. Новый проект ===")
    print(f"Проект: {project_name}")
    print(f"Режим картинок: {image_mode}")
    print(f"Конвертация видео: {'да' if convert_videos else 'нет'}")
    print(f"Шаги: структура → таблица → xml → авторы → картинки → видео → переименование → кроп → статьи")

    if not ask_confirm("Запустить?"):
        print("Отменено.")
        return

    run_core_pipeline(project_name)
    for task in tasks_for_all_run(image_mode, convert_videos=convert_videos):
        run_script_task(task, project_name=project_name, image_mode=image_mode)

    print("\n\033[32m=== Новый проект готов ===\033[0m")


def run_edits():
    """Flow 1: правки — выбирает существующий проект, парсит новую CSV, запускает пайплайн."""
    ensure_core_dependencies()
    projects = list_existing_projects()
    if not projects:
        print("Нет существующих проектов. Используйте '0. Новый проект'.")
        return

    options = [(name, name) for name in projects]
    project_name = select_option("Выберите проект для правок", options)
    os.environ["PROJECT_NAME"] = project_name

    image_mode = select_image_processing_mode()
    convert_videos = ask_confirm("Конвертировать скачанные видео в MP4 после загрузки?")

    upd_key = datetime.now().strftime("upd_%Y-%m-%d")
    print(f"\n=== 1. Правки: {project_name} | волна: {upd_key} ===")
    print("Шаги: новая таблица → xml → авторы → картинки → видео → переименование → кроп → статьи")
    print(f"Файлы этой волны пойдут в подпапки {upd_key}/")

    if not ask_confirm("Запустить?"):
        print("Отменено.")
        return

    os.environ["UPD_SUBDIR"] = upd_key

    # Структура уже создана — парсим новую CSV и обновляем только новые записи
    parse_links(project_name)
    create_xml_placeholders(project_name)
    enrich_channels(project_name)
    create_author_images(project_name)
    download_images(project_name)

    for task in tasks_for_all_run(image_mode, convert_videos=convert_videos):
        run_script_task(task, project_name=project_name, image_mode=image_mode)

    os.environ.pop("UPD_SUBDIR", None)
    print("\n\033[32m=== Правки завершены ===\033[0m")


def run_external_folder_crop_placeholder():
    """Кроп под 16:9 + placeholders_photo для произвольной папки с фото."""
    input_path = ask_text("Путь к папке с исходными фотографиями: ").strip().strip('"').strip("'")
    if not input_path:
        print("Путь не указан, отмена.")
        return
    input_dir = Path(input_path).expanduser().resolve()
    if not input_dir.exists():
        print(f"❌ Папка не найдена: {input_dir}")
        return

    cropped_dir = input_dir.parent / "images_cropped"

    crop_script = SCRIPTS_DIR / "2.1_smart_cropping.py"
    placeholder_script = SCRIPTS_DIR / "5_photo_placeholders.py"

    for script in (crop_script, placeholder_script):
        if not script.exists():
            print(f"❌ Скрипт не найден: {script}")
            return

    print(f"\n📥 Исходная папка:  {input_dir}")
    print(f"✂️  Кроп в папку:   {cropped_dir}")
    print(f"🎬 Плейсхолдеры:   {cropped_dir.parent / 'placeholders_photo'}")

    env = build_script_env()

    print(f"\n\033[36m=== Шаг 1/2: Кроп 16:9 ===\033[0m")
    run_command(
        [sys.executable, crop_script, "--input", str(input_dir), "--output", str(cropped_dir)],
        cwd=BASE_DIR,
        env=env,
        continue_on_error=False,
    )

    print(f"\n\033[36m=== Шаг 2/2: Photo placeholders ===\033[0m")
    run_command(
        [sys.executable, placeholder_script, "--input", str(cropped_dir)],
        cwd=BASE_DIR,
        env=env,
        continue_on_error=False,
    )

    print(f"\n\033[32m=== Готово! Плейсхолдеры: {cropped_dir.parent / 'placeholders_photo'} ===\033[0m")


def run_selected_task_menu():
    project_name = None
    image_mode = None

    while True:
        try:
            options = [
                ("Назад", "back"),
                (CORE_PIPELINE_TITLE, "core"),
                ("Кроп 16:9 + плейсхолдер из внешней папки", "external_folder"),
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
                run_core_pipeline(project_name)
                continue

            if choice == "external_folder":
                run_external_folder_crop_placeholder()
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

    Каждый вызов создаёт папку video_direct/{YYYY-MM-DD_HH-MM-SS}/
    Туда кладутся сами видео и PNG-плашки рядом.
    """
    ensure_core_dependencies()
    project_name = select_project_name()

    print("\nВведите ссылки на видео (по одной, пустая строка — начать скачивание):")
    urls: List[str] = []
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

    session_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    project_dir = Path(DATA_DIR) / project_name
    session_dir = project_dir / "video_direct" / session_ts
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n📁 Папка сессии: video_direct/{session_ts}/")
    print(f"📊 Видео к скачиванию: {len(urls)}")

    # Получаем метаданные каналов заранее (для плашек)
    req_session = requests.Session()
    logger = Logger()
    print("\n🔍 Получаю информацию о каналах...")
    url_meta: Dict[str, tuple] = {}
    for url in urls:
        channel, title = get_channel_and_title_for_url(req_session, url, logger)
        url_meta[url] = (channel, title)
        label = (title or url)[:60]
        print(f"  {label} → {channel or '?'}")

    cookies_file = str(BASE_DIR / "cookies.txt") if (BASE_DIR / "cookies.txt").exists() else None

    print(f"\n=== Скачивание ===")
    ok = fail = 0
    for idx, url in enumerate(urls, 1):
        channel, title = url_meta[url]
        label = (title or url)[:60]
        print(f"\n[{idx}/{len(urls)}] {label}")

        if _download_video_direct(url, session_dir, cookies_file):
            ok += 1
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip() if title else f"video_{idx:02d}"
            author_path = session_dir / f"{safe_title}_author.png"
            try:
                _make_author_png(channel, author_path)
                print(f"  ✅ Скачано | плашка: {author_path.name}")
            except Exception as e:
                print(f"  ✅ Скачано | ❌ плашка не создана: {e}")
        else:
            fail += 1
            print(f"  ❌ Ошибка скачивания")

    print(f"\n{'='*50}")
    print(f"Скачано: {ok}, ошибок: {fail}")
    print(f"📁 {session_dir}")


def main_menu():
    print("=== OSNOVATELI.DOC FRAMEWORK ===")

    while True:
        try:
            choice = select_option(
                "Главное меню",
                [
                    ("Установить ВСЕ зависимости", "install"),
                    ("0. Новый проект", "new_project"),
                    ("1. Правки проекта", "edits"),
                    ("2. Скачать видео по ссылкам", "direct_video"),
                    ("Скрипты по очереди", "scripts"),
                    ("Выход", "exit"),
                ],
            )
            if choice == "install":
                install_all_dependencies()
            elif choice == "new_project":
                run_new_project()
            elif choice == "edits":
                run_edits()
            elif choice == "direct_video":
                run_direct_video_download()
            elif choice == "scripts":
                run_selected_task_menu()
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
