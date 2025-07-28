import gspread
from google.oauth2.service_account import Credentials
import yt_dlp
import requests
import os
import re
import urllib.parse
import json
import subprocess
import sys

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

def check_and_install_dependencies():
    """
    Проверяет наличие необходимых зависимостей на macOS и устанавливает их через Homebrew при необходимости
    """
    print("=== ПРОВЕРКА ЗАВИСИМОСТЕЙ ===")
    
    # Проверяем наличие Homebrew
    try:
        subprocess.run(['brew', '--version'], check=True, capture_output=True)
        print("✓ Homebrew найден")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Homebrew не найден. Устанавливаем...")
        install_script = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        subprocess.run(install_script, shell=True, check=True)
        print("✓ Homebrew установлен")
    
    # Проверяем Python
    try:
        subprocess.run([sys.executable, '--version'], check=True, capture_output=True)
        print("✓ python3 найден")
    except subprocess.CalledProcessError:
        print("❌ Python3 не найден")
        return
    
    # Проверяем ffmpeg
    try:
        result = subprocess.run(['brew', 'list', 'ffmpeg'], capture_output=True)
        if result.returncode == 0:
            print("✓ ffmpeg найден")
        else:
            print("❌ ffmpeg не найден. Устанавливаем...")
            subprocess.run(['brew', 'install', 'ffmpeg'], check=True)
            print("✓ ffmpeg установлен")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при установке ffmpeg: {e}")
    
    # Проверяем chromium
    try:
        result = subprocess.run(['brew', 'list', 'chromium'], capture_output=True)
        if result.returncode == 0:
            print("✓ chromium найден")
        else:
            print("❌ chromium не найден. Устанавливаем...")
            subprocess.run(['brew', 'install', 'chromium'], check=True)
            print("✓ chromium установлен")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при установке chromium: {e}")
    
    # Проверяем yt-dlp
    try:
        # Сначала пробуем найти yt-dlp в системе
        result = subprocess.run(['which', 'yt-dlp'], capture_output=True)
        if result.returncode == 0:
            print("✓ yt-dlp найден в системе")
        else:
            # Если не найден, пробуем установить через pip
            print("❌ yt-dlp не найден. Устанавливаем через pip...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'yt-dlp'], check=True)
            print("✓ yt-dlp установлен через pip")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при установке yt-dlp: {e}")
        print("Пробуем установить через Homebrew...")
        try:
            subprocess.run(['brew', 'install', 'yt-dlp'], check=True)
            print("✓ yt-dlp установлен через Homebrew")
        except subprocess.CalledProcessError as e2:
            print(f"❌ Не удалось установить yt-dlp: {e2}")
            return
    
    print("=== ПРОВЕРКА ЗАВИСИМОСТЕЙ ЗАВЕРШЕНА ===\n")

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

# === ПРОВЕРКА ЗАВИСИМОСТЕЙ ===
check_and_install_dependencies()

# === НАСТРОЙКИ ===
SPREADSHEET_ID = extract_spreadsheet_id_from_url()
SHEET_NAME = 'Лист1'
COLUMN = get_column_from_user()
DOWNLOAD_DIR = os.path.expanduser('~/Downloads/youtube_videos')
# --- Новый блок: создаём поддиректорию для сохранения медиафайлов ---
from datetime import datetime as _dt
subdir_name = f"{COLUMN}_{_dt.now().strftime('%Y-%m-%d_%H-%M-%S')}"
MEDIA_DIR = os.path.join(DOWNLOAD_DIR, subdir_name)
os.makedirs(MEDIA_DIR, exist_ok=True)

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
    """Проверяет, является ли ссылка YouTube ссылкой"""
    youtube_patterns = [
        r'youtube\.com/watch\?v=',
        r'youtube\.com/embed/',
        r'youtube\.com/v/',
        r'youtu\.be/',
        r'youtube\.com/shorts/',
        r'youtube\.com/playlist\?list='
    ]
    return any(re.search(pattern, url) for pattern in youtube_patterns)

def extract_video_id(url):
    """Извлекает ID видео из YouTube ссылки"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtube\.com/embed/|youtube\.com/v/|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]+)',
        r'youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info_with_yt_dlp(url):
    """Получает информацию о видео с помощью yt-dlp"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        print(f"Ошибка при получении информации о видео: {e}")
        return None

def download_youtube_video(url, filename_template, row_num, idx):
    """Скачивает YouTube видео с улучшенными настройками"""
    
    # Базовые настройки для yt-dlp
    ydl_opts = {
        'outtmpl': os.path.join(MEDIA_DIR, filename_template),
        'format': 'best[ext=mp4]/best',  # Лучшее качество в MP4
        'merge_output_format': 'mp4',
        'writesubtitles': True,  # Скачиваем субтитры если есть
        'writeautomaticsub': True,
        'subtitleslangs': ['ru', 'en'],  # Русские и английские субтитры
        'writethumbnail': True,  # Скачиваем превью
        'writedescription': True,  # Скачиваем описание
        'writeinfojson': True,  # Скачиваем метаданные
        'ignoreerrors': False,
        'no_warnings': False,
        'verbose': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cookiefile': 'cookies.txt',  # Если есть файл с куками
        'extractor_args': {
            'youtube': {
                'skip': ['dash', 'hls'],  # Пропускаем DASH и HLS потоки
            }
        }
    }
    
    # Дополнительные настройки для разных типов контента
    if 'shorts' in url:
        ydl_opts['format'] = 'best[height<=1080]/best'  # Ограничиваем качество для shorts
    elif 'playlist' in url:
        ydl_opts['playlist_items'] = '1-10'  # Скачиваем первые 10 видео из плейлиста
    
    try:
        print(f"[YOUTUBE] Скачиваю {url}")
        print(f"[YOUTUBE] Файл будет сохранен как: {filename_template}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Сначала получаем информацию о видео
            info = ydl.extract_info(url, download=False)
            if info:
                print(f"[YOUTUBE] Название: {info.get('title', 'Неизвестно')}")
                print(f"[YOUTUBE] Длительность: {info.get('duration', 'Неизвестно')} сек")
                print(f"[YOUTUBE] Качество: {info.get('format', 'Неизвестно')}")
            
            # Скачиваем видео
            ydl.download([url])
            
            print(f"[YOUTUBE] ✓ Успешно скачано: {url}")
            return True
            
    except Exception as e:
        print(f"[YOUTUBE] Ошибка при скачивании {url}: {e}")
        
        # Попробуем альтернативные форматы
        print(f"[YOUTUBE] Пробую альтернативные настройки для {url}")
        try:
            ydl_opts['format'] = 'best'  # Просто лучшее качество
            ydl_opts['merge_output_format'] = 'mp4'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                print(f"[YOUTUBE] ✓ Успешно скачано с альтернативными настройками: {url}")
                return True
        except Exception as e2:
            print(f"[YOUTUBE] Ошибка при повторной попытке {url}: {e2}")
            return False

def sanitize_filename(title, row_num, idx, column=None):
    """Создает безопасное имя файла из названия видео"""
    # Убираем недопустимые символы
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
    safe_title = re.sub(r'\s+', '_', safe_title)
    safe_title = safe_title[:100]  # Ограничиваем длину
    
    cell_ref = f"{column}{row_num}" if column else str(row_num)
    return f"{cell_ref}_{idx}_{safe_title}.%(ext)s"

def log_failed_download(url, error_msg, cell_ref=None, idx=None):
    """Логирует неудачные попытки скачивания"""
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"youtube_download_errors_{now}.txt"
    error_dir = os.path.join(MEDIA_DIR, 'download_errors')
    os.makedirs(error_dir, exist_ok=True)
    filepath = os.path.join(error_dir, filename)
    
    with open(filepath, 'a', encoding='utf-8') as f:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if cell_ref and idx is not None:
            f.write(f"[{timestamp}] {cell_ref} [{idx}]: {url} - {error_msg}\n")
        elif cell_ref:
            f.write(f"[{timestamp}] {cell_ref}: {url} - {error_msg}\n")
        else:
            f.write(f"[{timestamp}] {url} - {error_msg}\n")

def count_youtube_links_in_column(data):
    """Подсчитывает количество YouTube ссылок в колонке"""
    total = 0
    for cell in data:
        links = re.findall(r'https?://[^\s,;"\'<>]+', cell)
        for link in links:
            if is_youtube_url(link):
                total += 1
    return total

def print_progress_bar(current, total, bar_length=40):
    """Показывает прогресс скачивания"""
    percent = float(current) / total if total else 0
    arrow = '-' * int(round(percent * bar_length) - 1) + '>' if percent > 0 else ''
    spaces = ' ' * (bar_length - len(arrow))
    print(f'\rПрогресс: [{arrow}{spaces}] {current}/{total}', end='')
    if current == total:
        print()

# Основной цикл скачивания
total_youtube_links = count_youtube_links_in_column(data)
processed_links = 0

print(f"\n=== НАЧАЛО СКАЧИВАНИЯ YOUTUBE ВИДЕО ===")
print(f"Найдено YouTube ссылок: {total_youtube_links}")
print(f"Папка для сохранения: {MEDIA_DIR}")
print(f"Колонка: {COLUMN}")
print("=" * 50)

for i, cell in enumerate(data, 1):
    if cell.strip():
        links = re.findall(r'https?://[^\s,;"\'<>]+', cell)
        for idx, url in enumerate(links, 1):
            if is_youtube_url(url):
                cell_ref = f"{COLUMN}{i}"
                
                # Получаем информацию о видео для лучшего именования файла
                video_info = get_video_info_with_yt_dlp(url)
                if video_info and video_info.get('title'):
                    filename_template = sanitize_filename(video_info['title'], i, idx, COLUMN)
                else:
                    # Если не удалось получить название, используем стандартное именование
                    filename_template = f"{cell_ref}_{idx}.%(ext)s" if len(links) > 1 else f"{cell_ref}.%(ext)s"
                
                # Скачиваем видео
                success = download_youtube_video(url, filename_template, i, idx)
                
                if not success:
                    log_failed_download(url, "Не удалось скачать видео", cell_ref, idx)
                
                processed_links += 1
                print_progress_bar(processed_links, total_youtube_links)

def collect_all_download_errors():
    """Собирает все ошибки скачивания в один файл"""
    import glob
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    error_dir = os.path.join(MEDIA_DIR, 'download_errors')
    all_files = glob.glob(os.path.join(error_dir, 'youtube_download_errors_*.txt'))
    if not all_files:
        print('Нет файлов с ошибками скачивания для объединения.')
        return
    out_path = os.path.join(error_dir, f'all_youtube_errors_{now}.txt')
    with open(out_path, 'w', encoding='utf-8') as outfile:
        for fname in all_files:
            with open(fname, 'r', encoding='utf-8') as infile:
                outfile.write(f'--- {os.path.basename(fname)} ---\n')
                outfile.write(infile.read())
                outfile.write('\n')
    print(f'Все ошибки скачивания собраны в {out_path}')

print("\n" + "=" * 50)
print("СКАЧИВАНИЕ ЗАВЕРШЕНО!")
print(f"Обработано ссылок: {processed_links}")
print(f"Файлы сохранены в: {MEDIA_DIR}")
print("=" * 50)

collect_all_download_errors() 