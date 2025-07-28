import gspread
from google.oauth2.service_account import Credentials
import yt_dlp
import requests
import os
import re
import urllib.parse
import json

from bs4 import BeautifulSoup

# Для selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import base64

from dotenv import load_dotenv
import datetime

def extract_spreadsheet_id_from_url():
    """
    Запрашивает у пользователя ссылку на Google таблицу и извлекает из неё SPREADSHEET_ID
    """
    while True:
        print("\n=== ВВОД ССЫЛКИ НА GOOGLE ТАБЛИЦУ ===")
        print("Скопируйте ссылку на Google таблицу из браузера.")
        print("Примеры ссылок:")
        print("- https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit")
        print("- https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0")
        
        url = input("\nВведите ссылку на Google таблицу: ").strip()
        
        if not url:
            print("Ошибка: ссылка не может быть пустой. Попробуйте снова.")
            continue
            
        # Извлекаем SPREADSHEET_ID из ссылки
        # Паттерн для поиска ID в ссылке Google Sheets
        pattern = r'/spreadsheets/d/([a-zA-Z0-9-_]+)'
        match = re.search(pattern, url)
        
        if match:
            spreadsheet_id = match.group(1)
            print(f"✓ SPREADSHEET_ID успешно извлечен: {spreadsheet_id}")
            return spreadsheet_id
        else:
            print("Ошибка: не удалось извлечь SPREADSHEET_ID из ссылки.")
            print("Убедитесь, что ссылка корректная и содержит ID таблицы.")
            print("Попробуйте снова.")

def get_column_from_user():
    while True:
        col = input('Введите латинскую заглавную букву колонки таблицы (например, B): ').strip().upper()
        if len(col) == 1 and 'A' <= col <= 'Z':
            return col
        print('Ошибка: введите одну латинскую заглавную букву (A-Z).')

# === НАСТРОЙКИ ===
SPREADSHEET_ID = extract_spreadsheet_id_from_url()
# CREDENTIALS_FILE = '/Users/theseus/ASSETS/data_files/2.json'  # больше не нужен
SHEET_NAME = 'Лист1'
COLUMN = get_column_from_user()
DOWNLOAD_DIR = os.path.expanduser('~/Downloads/media_from_sheet')
# --- Новый блок: создаём поддиректорию для сохранения медиафайлов ---
from datetime import datetime as _dt
subdir_name = f"{COLUMN}_{_dt.now().strftime('%Y-%m-%d_%H-%M-%S')}"
MEDIA_DIR = os.path.join(DOWNLOAD_DIR, subdir_name)
os.makedirs(MEDIA_DIR, exist_ok=True)
TOR_PORT = 9150  # или 9050, если у вас системный Tor
TOR_PROXY = f'socks5h://127.0.0.1:{TOR_PORT}'

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

load_dotenv()

# === АВТОРИЗАЦИЯ ===
scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
service_account_info = {
    "type": os.getenv("TYPE"),
    "project_id": os.getenv("PROJECT_ID"),
    "private_key_id": os.getenv("PRIVATE_KEY_ID"),
    "private_key": os.getenv("PRIVATE_KEY").replace('\\n', '\n'),
    "client_email": os.getenv("CLIENT_EMAIL"),
    "client_id": os.getenv("CLIENT_ID"),
    "auth_uri": os.getenv("AUTH_URI"),
    "token_uri": os.getenv("TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL"),
    "universe_domain": os.getenv("UNIVERSE_DOMAIN"),
}
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
gc = gspread.authorize(creds)

# === ЧТЕНИЕ ТАБЛИЦЫ ===
sh = gc.open_by_key(SPREADSHEET_ID)
worksheet = sh.worksheet(SHEET_NAME)
data = worksheet.col_values(ord(COLUMN.upper()) - ord('A') + 1)

def is_youtube_url(url):
    return 'youtube.com' in url or 'youtu.be' in url

def is_video_url(url):
    video_domains = [
        'youtube.com', 'youtu.be', 'vimeo.com', 'vk.com/video', 'rutube.ru', 'dailymotion.com',
        'tiktok.com', 'facebook.com', 'bilibili.com', 'ok.ru', 'dzen.ru', 'instagram.com'
    ]
    for domain in video_domains:
        if domain in url:
            return True
    video_exts = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv']
    if any(url.lower().split('?')[0].endswith(ext) for ext in video_exts):
        return True
    return False

def is_image_url(url):
    image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff']
    if any(url.lower().split('?')[0].endswith(ext) for ext in image_exts):
        return True
    if 'images.app.goo.gl' in url:
        return True
    return False

def is_news_url(url):
    news_domains = [
        'starhit.ru', 'rbc.ru', 'rambler.ru'
    ]
    return any(domain in url for domain in news_domains)

def get_direct_image_url(url):
    """Если это images.app.goo.gl, пытаемся получить прямую ссылку через selenium"""
    if 'images.app.goo.gl' not in url:
        return url
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        driver.get(url)
        time.sleep(5)
        images = driver.find_elements(By.TAG_NAME, 'img')
        for img in images:
            src = img.get_attribute('src')
            if src and src.startswith('http') and ('.jpg' in src or '.png' in src or '.webp' in src):
                return src
    finally:
        driver.quit()
    return None

def sanitize_filename(url, row_num, idx, is_image=True, column=None):
    ext = os.path.splitext(url.split('?')[0])[1]
    if not ext or len(ext) > 5:
        ext = '.jpg' if is_image else '.mp4'
    cell_ref = f"{column}{row_num}" if column else str(row_num)
    return f"{cell_ref}_{idx}{ext}"

def get_yandex_video_original_url(yandex_url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(yandex_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"Не удалось открыть {yandex_url} (status {resp.status_code})")
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # 1. Ищем iframe
        iframe = soup.find("iframe")
        if iframe and iframe.has_attr("src"):
            iframe_src = iframe["src"]
            # Если это ok.ru/videoembed или youtube, возвращаем
            if "ok.ru/videoembed" in iframe_src or "youtube.com" in iframe_src or "rutube.ru" in iframe_src:
                return iframe_src
            # Если это yastatic.net/video-player, парсим параметры
            if "yastatic.net/video-player" in iframe_src:
                # Парсим параметры из ссылки
                parsed = urllib.parse.urlparse(iframe_src)
                params = urllib.parse.parse_qs(parsed.query)
                # 1. В параметре html может быть iframe с src
                if "html" in params:
                    html_raw = params["html"][0]
                    html_decoded = urllib.parse.unquote(html_raw)
                    # Ищем src="..."
                    m = re.search(r'src="([^"]+)"', html_decoded)
                    if m:
                        src_url = m.group(1)
                        # Иногда бывает много слэшей, уберём лишние
                        src_url = src_url.replace("////", "//")
                        if src_url.startswith("//"):
                            src_url = "https:" + src_url
                        return src_url
                # 2. В параметре counters может быть videoUrl
                if "counters" in params:
                    counters_raw = params["counters"][0]
                    try:
                        counters_json = json.loads(urllib.parse.unquote(counters_raw))
                        if "videoUrl" in counters_json:
                            return counters_json["videoUrl"]
                    except Exception:
                        pass
            # Если просто ссылка на ok.ru, возвращаем
            if "ok.ru/video" in iframe_src:
                return iframe_src
        # 2. Ищем ссылку на оригинал (например, YouTube)
        for a in soup.find_all("a", href=True):
            if any(domain in a["href"] for domain in [
                "youtube.com", "youtu.be", "vk.com", "rutube.ru", "ok.ru", "dzen.ru", "vimeo.com"
            ]):
                return a["href"]
        # 3. Иногда ссылка есть в meta
        for meta in soup.find_all("meta", attrs={"property": "og:video:url"}):
            if meta.has_attr("content"):
                return meta["content"]
        return None
    except Exception as e:
        print(f"Ошибка при парсинге {yandex_url}: {e}")
        return None

def log_unrecognized_url(url, cell_ref=None, idx=None):
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"parse_error_{now}.txt"
    error_dir = os.path.join(MEDIA_DIR, 'parse_error')
    os.makedirs(error_dir, exist_ok=True)
    filepath = os.path.join(error_dir, filename)
    with open(filepath, 'a', encoding='utf-8') as f:
        if cell_ref and idx is not None:
            f.write(f"{cell_ref} [{idx}]: {url}\n")
        elif cell_ref:
            f.write(f"{cell_ref}: {url}\n")
        else:
            f.write(url + '\n')

def count_links_in_column(data):
    total = 0
    for cell in data:
        links = re.findall(r'https?://[^\s,;"\'<>]+', cell)
        total += len(links)
    return total

def print_progress_bar(current, total, bar_length=40):
    percent = float(current) / total if total else 0
    arrow = '-' * int(round(percent * bar_length) - 1) + '>' if percent > 0 else ''
    spaces = ' ' * (bar_length - len(arrow))
    print(f'\rПрогресс: [{arrow}{spaces}] {current}/{total}', end='')
    if current == total:
        print()

total_links = count_links_in_column(data)
processed_links = 0

for i, cell in enumerate(data, 1):
    if cell.strip():
        links = re.findall(r'https?://[^\s,;"\'<>]+', cell)
        for idx, url in enumerate(links, 1):
            # --- Новый блок для Яндекс.Видео ---
            if "yandex.ru/video/" in url:
                print(f"[YANDEX] Парсим оригинал для {url}")
                orig_url = get_yandex_video_original_url(url)
                if orig_url:
                    print(f"Найден оригинал: {orig_url}")
                    url = orig_url
                else:
                    print(f"Не удалось найти оригинал для {url}")
                    continue
            # --- Дальше как обычно ---
            if is_video_url(url):
                cell_ref = f"{COLUMN}{i}"
                filename = f"{cell_ref}_{idx}.%(ext)s" if len(links) > 1 else f"{cell_ref}.%(ext)s"
                ydl_opts = {
                    'outtmpl': os.path.join(MEDIA_DIR, filename),
                    'concurrent_fragment_downloads': 8,
                    'fragment_retries': 10,
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4',
                    'merge_output_format': 'mp4',
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
                if is_youtube_url(url):
                    ydl_opts['proxy'] = TOR_PROXY
                    print(f"[ВИДЕО] Скачиваю {url} как {filename} через Tor ({TOR_PROXY})")
                else:
                    print(f"[ВИДЕО] Скачиваю {url} как {filename} напрямую")
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except Exception as e:
                    err_str = str(e)
                    print(f"Ошибка при скачивании видео {url}: {e}")
                    # Логируем неудачную попытку скачивания видео
                    log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
                    # --- Новый обработчик: если ошибка 'There is no video in this post', пробуем скачать картинку ---
                    if 'There is no video in this post' in err_str:
                        print(f"[INSTAGRAM] Видео не найдено, пробую скачать картинку из поста {url}")
                        try:
                            headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            }
                            resp = requests.get(url, headers=headers, timeout=15)
                            if resp.status_code == 200:
                                soup = BeautifulSoup(resp.text, 'html.parser')
                                img_url = None
                                # Ищем <meta property="og:image" ...>
                                meta = soup.find('meta', property='og:image')
                                if meta and meta.get('content'):
                                    img_url = meta['content']
                                # Если не нашли, ищем <img>
                                if not img_url:
                                    img = soup.find('img')
                                    if img and img.get('src'):
                                        img_url = img['src']
                                if img_url:
                                    img_filename = sanitize_filename(img_url, i, idx, is_image=True, column=COLUMN)
                                    filepath = os.path.join(MEDIA_DIR, img_filename)
                                    img_resp = requests.get(img_url, headers=headers, timeout=15)
                                    if img_resp.status_code == 200:
                                        with open(filepath, 'wb') as f:
                                            f.write(img_resp.content)
                                        print(f"Скачано: {filepath}")
                                    else:
                                        print(f"Не удалось скачать картинку {img_url} (status {img_resp.status_code})")
                                        log_unrecognized_url(img_url, cell_ref=cell_ref, idx=idx)
                                else:
                                    print(f"Картинка не найдена на странице {url}")
                                    log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
                            else:
                                print(f"Не удалось получить страницу {url} (status {resp.status_code})")
                                log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
                        except Exception as e2:
                            print(f"Ошибка при скачивании картинки из поста Instagram: {e2}")
                            log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
            elif is_image_url(url):
                print(f"[КАРТИНКА] Обрабатываю строку {i}, ссылка {url}")
                direct_url = get_direct_image_url(url)
                if not direct_url:
                    print(f"Не удалось получить прямую ссылку для {url}")
                    cell_ref = f"{COLUMN}{i}"
                    log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
                    continue
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    response = requests.get(direct_url, headers=headers, timeout=15)
                    if response.status_code == 200 and response.headers['Content-Type'].startswith('image'):
                        filename = sanitize_filename(direct_url, i, idx, is_image=True, column=COLUMN)
                        filepath = os.path.join(MEDIA_DIR, filename)
                        with open(filepath, 'wb') as f:
                            f.write(response.content)
                        print(f"Скачано: {filepath}")
                    else:
                        print(f"Не удалось скачать {direct_url} (status {response.status_code})")
                        cell_ref = f"{COLUMN}{i}"
                        log_unrecognized_url(direct_url, cell_ref=cell_ref, idx=idx)
                except Exception as e:
                    print(f"Ошибка при скачивании {direct_url}: {e}")
                    cell_ref = f"{COLUMN}{i}"
                    log_unrecognized_url(direct_url, cell_ref=cell_ref, idx=idx)
            elif is_news_url(url):
                # Просто логируем ссылку в parse error
                cell_ref = f"{COLUMN}{i}"
                log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
            else:
                print(f"[?] Неизвестный тип ссылки: {url}")
                cell_ref = f"{COLUMN}{i}"
                log_unrecognized_url(url, cell_ref=cell_ref, idx=idx)
            processed_links += 1
            print_progress_bar(processed_links, total_links)

def collect_all_parse_errors():
    import glob
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    error_dir = os.path.join(MEDIA_DIR, 'parse_error')
    all_files = glob.glob(os.path.join(error_dir, 'parse_error_*.txt'))
    if not all_files:
        print('Нет файлов parse_error для объединения.')
        return
    out_path = os.path.join(error_dir, f'all_parse_errors_{now}.txt')
    with open(out_path, 'w', encoding='utf-8') as outfile:
        for fname in all_files:
            with open(fname, 'r', encoding='utf-8') as infile:
                outfile.write(f'--- {os.path.basename(fname)} ---\n')
                outfile.write(infile.read())
                outfile.write('\n')
    print(f'Все parse_error собраны в {out_path}')

print("Готово!")
collect_all_parse_errors()