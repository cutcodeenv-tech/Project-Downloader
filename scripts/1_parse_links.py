import gspread
from google.oauth2.service_account import Credentials
import os
import re
import urllib.parse
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

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

def get_project_name():
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

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
    
    # Проверяем домены Яндекс.Видео
    if 'yandex.ru/video' in url:
        return True
    
    # Проверяем расширения видео файлов
    video_exts = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.m4v', '.3gp']
    if any(url.lower().split('?')[0].endswith(ext) for ext in video_exts):
        return True
    
    return False

def is_image_url(url):
    # Проверяем домены изображений
    image_domains = [
        'images.app.goo.gl', 'avatars.mds.yandex.net', 'avatars.dzeninfra.ru',
        'cdn.i.haymarketmedia.asia', 'images.steamusercontent.com', 'play-lh.googleusercontent.com'
    ]
    for domain in image_domains:
        if domain in url:
            return True
    
    # Проверяем расширения изображений
    image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']
    if any(url.lower().split('?')[0].endswith(ext) for ext in image_exts):
        return True
    
    # Проверяем параметры в URL, указывающие на изображения
    image_params = ['scale_', 'resize', 'XXXL', 'diploma', 'thumbs']
    for param in image_params:
        if param in url:
            return True
    
    return False

def check_content_type_by_headers(url):
    """Проверяет тип контента по HTTP заголовкам"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            
            # Проверяем изображения
            if any(img_type in content_type for img_type in ['image/', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']):
                return 'image'
            
            # Проверяем видео
            if any(video_type in content_type for video_type in ['video/', 'video/mp4', 'video/webm', 'video/avi']):
                return 'video'
            
            # Проверяем HTML (новостные статьи)
            if 'text/html' in content_type:
                return 'news'
        
        return None
    except Exception as e:
        print(f"Ошибка при проверке заголовков для {url}: {e}")
        return None

def is_news_url(url):
    news_domains = [
        'starhit.ru', 'rbc.ru', 'rambler.ru'
    ]
    return any(domain in url for domain in news_domains)

def sanitize_filename(url, row_num, idx, column=None):
    cell_ref = f"{column}{row_num}" if column else str(row_num)
    return f"{cell_ref}_{idx}"

def categorize_url(url):
    """Категоризирует URL по типу контента"""
    # Сначала проверяем по URL паттернам
    if is_video_url(url):
        return 'video'
    elif is_image_url(url):
        return 'image'
    else:
        # Если не удалось определить по URL, проверяем по HTTP заголовкам
        content_type = check_content_type_by_headers(url)
        if content_type:
            return content_type
        else:
            # Если и заголовки не помогли, проверяем, является ли это HTML страницей
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if 'text/html' in content_type:
                        return 'news'
            except:
                pass
            # Если ничего не подошло, считаем новостной статьей
            return 'news'

def categorize_url_with_errors(url, cell_ref=None, idx=None, parse_errors_file_path=None):
    """Категоризирует URL и логирует нераспознанные ссылки"""
    category = categorize_url(url)
    
    # Если ссылка не попала ни в одну категорию, логируем её
    if category == 'news' and not is_news_url(url):
        # Проверяем, действительно ли это новостная статья
        if parse_errors_file_path:
            log_parse_error(url, cell_ref, idx, parse_errors_file_path)
        return 'news'  # Все равно возвращаем как новость
    
    return category

def log_unrecognized_url(url, cell_ref=None, idx=None, error_file_path=None):
    """Логирует нераспознанные ссылки в файл ошибок"""
    if error_file_path:
        with open(error_file_path, 'a', encoding='utf-8') as f:
            if cell_ref and idx is not None:
                f.write(f"{cell_ref} [{idx}]: {url}\n")
            elif cell_ref:
                f.write(f"{cell_ref}: {url}\n")
            else:
                f.write(url + '\n')

def log_parse_error(url, cell_ref=None, idx=None, error_file_path=None):
    """Логирует ссылки, которые не удалось распознать ни в одну категорию"""
    if error_file_path:
        with open(error_file_path, 'a', encoding='utf-8') as f:
            if cell_ref and idx is not None:
                f.write(f"{cell_ref} [{idx}]: {url}\n")
            elif cell_ref:
                f.write(f"{cell_ref}: {url}\n")
            else:
                f.write(url + '\n')

def main():
    print("=== СКРИПТ ПАРСИНГА ССЫЛОК ИЗ GOOGLE ТАБЛИЦЫ ===")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Запрашиваем ссылку на таблицу
    spreadsheet_id = extract_spreadsheet_id_from_url()
    
    # Запрашиваем колонку
    column = get_column_from_user()
    
    # Создаем структуру директорий
    downloads_dir = os.path.expanduser('~/Downloads')
    download_all_dir = os.path.join(downloads_dir, 'download_all')
    project_dir = os.path.join(download_all_dir, project_name)
    parse_links_dir = os.path.join(project_dir, '1_parse_links')
    
    # Создаем директории
    os.makedirs(parse_links_dir, exist_ok=True)
    
    # Создаем файл для ошибок
    error_file_path = os.path.join(parse_links_dir, 'parse_links_errors.txt')
    parse_errors_file_path = os.path.join(parse_links_dir, 'parse_errors.txt')
    
    # Загружаем переменные окружения
    load_dotenv()
    
    # Настройки для Google Sheets API
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
    
    # Авторизация
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    gc = gspread.authorize(creds)
    
    # Чтение таблицы
    sh = gc.open_by_key(spreadsheet_id)
    worksheet = sh.worksheet('Лист1')
    data = worksheet.col_values(ord(column.upper()) - ord('A') + 1)
    
    # Словари для группировки ссылок
    categorized_links = {
        'image': [],
        'video': [],
        'news': []
    }
    
    print(f"\n=== ПАРСИНГ ССЫЛОК ИЗ КОЛОНКИ {column} ===")
    
    # Обрабатываем каждую ячейку
    for i, cell in enumerate(data, 1):
        if cell.strip():
            links = re.findall(r'https?://[^\s,;"\'<>]+', cell)
            for idx, url in enumerate(links, 1):
                category = categorize_url_with_errors(url, f"{column}{i}", idx, parse_errors_file_path)
                # Создаем имя файла в том же стиле, что и в download_all
                filename = sanitize_filename(url, i, idx, column=column)
                categorized_links[category].append({
                    'url': url,
                    'filename': filename,
                    'cell_ref': f"{column}{i}",
                    'index': idx
                })
                print(f"[{category.upper()}] {filename}: {url}")
    
    # Сохраняем результаты в файлы
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    for category, links in categorized_links.items():
        if links:
            filename = f"{category}_links_{timestamp}.txt"
            filepath = os.path.join(parse_links_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Ссылки категории: {category}\n")
                f.write(f"# Дата создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Колонка: {column}\n")
                f.write(f"# Всего ссылок: {len(links)}\n\n")
                
                for link_info in links:
                    f.write(f"{link_info['filename']} {link_info['url']}\n")
            
            print(f"\n✓ Сохранено {len(links)} ссылок категории '{category}' в файл: {filename}")
    

    
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Проект: {project_name}")
    print(f"Директория: {parse_links_dir}")
    print(f"Изображения: {len(categorized_links['image'])} ссылок")
    print(f"Видео: {len(categorized_links['video'])} ссылок")
    print(f"Новости: {len(categorized_links['news'])} ссылок")
    total_links = len(categorized_links['image']) + len(categorized_links['video']) + len(categorized_links['news'])
    print(f"Всего: {total_links} ссылок")

if __name__ == "__main__":
    main()
