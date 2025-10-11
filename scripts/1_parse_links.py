import gspread
from google.oauth2.service_account import Credentials
import os
import re
import urllib.parse
import json
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv

def resolve_worksheet(sh):
    """Возвращает рабочий лист, устойчиво к различным названиям листов.
    Порядок выбора:
    1) Попытка по популярным названиям ('Лист1', 'Sheet1', 'Sheet', 'Лист')
    2) Первый лист в таблице
    3) Интерактивный выбор пользователя из доступных названий
    """
    preferred_titles = ['\u041b\u0438\u0441\u04421', 'Sheet1', 'Sheet', '\u041b\u0438\u0441\u0442']
    for title in preferred_titles:
        try:
            return sh.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            pass

    # Пытаемся взять первый лист
    try:
        return sh.sheet1
    except Exception:
        pass

    # Если ничего не нашли, предлагаем пользователю выбрать из списка
    try:
        worksheets = sh.worksheets()
        titles = [ws.title for ws in worksheets]
        if titles:
            print("Доступные листы: " + ", ".join(titles))
            while True:
                user_title = input("Введите название листа из списка выше: ").strip()
                if not user_title:
                    print("Название не может быть пустым. Попробуйте снова.")
                    continue
                try:
                    return sh.worksheet(user_title)
                except gspread.exceptions.WorksheetNotFound:
                    print("Лист не найден. Проверьте раскладку/регистр и попробуйте снова.")
    except Exception:
        pass

    # Финальный случай: явно сообщаем об ошибке
    raise gspread.exceptions.WorksheetNotFound("Не удалось определить рабочий лист.")

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
        
        # Показываем сервисный email для шаринга
        print("\n⚠️  ВАЖНО: Убедитесь, что таблица расшарена на сервисный email!")
        service_email = get_service_email()
        print(f"📧 Сервисный email для шаринга: {service_email}")
        print("   Дайте этому email доступ 'Читатель' к таблице")
        
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

def get_service_email():
    """Получает сервисный email из переменных окружения"""
    load_dotenv()
    service_email = os.getenv("CLIENT_EMAIL")
    if not service_email:
        print("⚠️  Предупреждение: CLIENT_EMAIL не найден в переменных окружения")
        return "неизвестен"
    return service_email

def extract_links_from_csv_column_b(database_dir):
    """Извлекает ссылки из колонки B сохраненного CSV файла"""
    print(f"\n=== ПОИСК ССЫЛОК В КОЛОНКЕ B ===")
    
    input_gdoc_file = os.path.join(database_dir, 'input_gdoc.csv')
    
    if not os.path.exists(input_gdoc_file):
        print(f"Ошибка: файл {input_gdoc_file} не найден")
        return []
    
    all_links = []
    
    try:
        with open(input_gdoc_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)
            
            # Обрабатываем каждую строку (колонка B = индекс 1)
            for row_num, row in enumerate(rows, 1):
                if len(row) > 1 and row[1].strip():  # Проверяем, что есть колонка B
                    cell_content = row[1].strip()
                    links = re.findall(r'https?://[^\s,;"\'<>]+', cell_content)
                    
                    for idx, url in enumerate(links, 1):
                        link_info = {
                            'source_address': f"B{row_num}_{idx}",
                            'url': url,
                            'cell_ref': f"B{row_num}",
                            'link_number': idx,
                            'display_name': f"B{row_num}_{idx}"
                        }
                        all_links.append(link_info)
                        print(f"[{link_info['display_name']}] {url}")
        
        print(f"\n✓ Найдено {len(all_links)} ссылок в колонке B")
        return all_links
        
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}")
        return []

def get_project_name():
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def is_youtube_url(url):
    """Проверяет, является ли ссылка YouTube ссылкой"""
    return 'youtube.com' in url or 'youtu.be' in url

def is_image_url(url):
    """Проверяет, является ли ссылка ссылкой на изображение"""
    # Проверяем домены изображений
    image_domains = [
        'images.app.goo.gl', 'avatars.mds.yandex.net', 'avatars.dzeninfra.ru',
        'cdn.i.haymarketmedia.asia', 'images.steamusercontent.com', 'play-lh.googleusercontent.com',
        'share.google'
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

def is_video_url(url):
    """Проверяет, является ли ссылка ссылкой на видео (кроме YouTube)"""
    video_domains = [
        'vimeo.com', 'vk.com/video', 'rutube.ru', 'dailymotion.com',
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
        
        return None
    except Exception as e:
        print(f"Ошибка при проверке заголовков для {url}: {e}")
        return None

def categorize_url(url):
    """Категоризирует URL по типу контента"""
    # Сначала проверяем YouTube
    if is_youtube_url(url):
        return 'youtube'
    # Затем проверяем изображения
    elif is_image_url(url):
        return 'image'
    # Затем проверяем видео (кроме YouTube)
    elif is_video_url(url):
        return 'video'
    else:
        # Если не удалось определить по URL, проверяем по HTTP заголовкам
        content_type = check_content_type_by_headers(url)
        if content_type:
            return content_type
        else:
            # Если ничего не подошло, считаем остальными ссылками
            return 'other'

def save_table_structure_to_csv(spreadsheet_id, database_dir):
    """Сохраняет полную структуру таблицы в input_gdoc.csv"""
    print(f"\n=== СОХРАНЕНИЕ СТРУКТУРЫ ТАБЛИЦЫ ===")
    
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
    worksheet = resolve_worksheet(sh)
    
    # Получаем все данные из таблицы
    all_values = worksheet.get_all_values()
    
    # Сохраняем в CSV
    input_gdoc_file = os.path.join(database_dir, 'input_gdoc.csv')
    with open(input_gdoc_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        for row in all_values:
            writer.writerow(row)
    
    print(f"✓ Структура таблицы сохранена в: input_gdoc.csv")
    print(f"✓ Строк в таблице: {len(all_values)}")
    return all_values

def save_links_to_csv(all_links, database_dir, project_name):
    """Сохраняет найденные ссылки в CSV файл"""
    if not all_links:
        print("Нет ссылок для сохранения")
        return
    
    # Сохраняем все ссылки в CSV
    all_links_file = os.path.join(database_dir, f'osnovateli_doc_{project_name}_all_links.csv')
    with open(all_links_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['source_address', 'url'])  # Заголовки
        for link_info in all_links:
            writer.writerow([link_info['source_address'], link_info['url']])
    
    print(f"\n✓ Сохранено {len(all_links)} ссылок в файл: osnovateli_doc_{project_name}_all_links.csv")

def categorize_links_from_csv(all_links, database_dir, project_name):
    """Категоризирует ссылки из CSV файла по типам и сохраняет в отдельные CSV"""
    print(f"\n=== КАТЕГОРИЗАЦИЯ ССЫЛОК ===")
    
    # Словари для группировки ссылок
    categorized_links = {
        'image': [],
        'youtube': [],
        'video': [],
        'other': []
    }
    
    # Категоризируем ссылки
    for link_info in all_links:
        category = categorize_url(link_info['url'])
        categorized_links[category].append({
            'source_address': link_info['source_address'],
            'url': link_info['url']
        })
        print(f"[{category.upper()}] {link_info['source_address']}: {link_info['url']}")
    
    # Сохраняем результаты в отдельные CSV файлы
    for category, links in categorized_links.items():
        if links:
            filename = f"osnovateli_doc_{project_name}_{category}_links.csv"
            filepath = os.path.join(database_dir, filename)
            
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['source_address', 'url'])  # Заголовки
                for link_info in links:
                    writer.writerow([link_info['source_address'], link_info['url']])
            
            print(f"\n✓ Сохранено {len(links)} ссылок категории '{category}' в файл: {filename}")
    
    return categorized_links

def main():
    print("=== СКРИПТ ПАРСИНГА ССЫЛОК ИЗ GOOGLE ТАБЛИЦЫ ===")
    
    # Показываем сервисный email в начале
    print("\n📧 ИНФОРМАЦИЯ О ДОСТУПЕ К ТАБЛИЦЕ:")
    service_email = get_service_email()
    print(f"   Сервисный email: {service_email}")
    print("   Убедитесь, что Google таблица расшарена на этот email с правами 'Читатель'")
    print("   Если таблица не расшарена, скрипт не сможет получить к ней доступ")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Запрашиваем ссылку на таблицу
    spreadsheet_id = extract_spreadsheet_id_from_url()
    
    # Создаем структуру директорий в data/
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    
    # Создаем директории
    os.makedirs(database_dir, exist_ok=True)
    print(f"✓ Рабочая директория: {database_dir}")
    
    # Этап 1: Сохранение структуры таблицы
    table_structure = save_table_structure_to_csv(spreadsheet_id, database_dir)
    
    # Этап 2: Автоматический поиск ссылок в колонке B
    all_links = extract_links_from_csv_column_b(database_dir)
    
    # Этап 3: Сохранение всех ссылок в CSV
    save_links_to_csv(all_links, database_dir, project_name)
    
    # Этап 4: Категоризация ссылок
    categorized_links = categorize_links_from_csv(all_links, database_dir, project_name)
    
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Проект: {project_name}")
    print(f"Директория: {database_dir}")
    print(f"Изображения: {len(categorized_links['image'])} ссылок")
    print(f"YouTube: {len(categorized_links['youtube'])} ссылок")
    print(f"Видео (другие): {len(categorized_links['video'])} ссылок")
    print(f"Остальные: {len(categorized_links['other'])} ссылок")
    total_links = sum(len(links) for links in categorized_links.values())
    print(f"Всего: {total_links} ссылок")
    
    print(f"\n=== СОЗДАННЫЕ ФАЙЛЫ ===")
    print(f"✓ input_gdoc.csv - полная структура таблицы")
    print(f"✓ osnovateli_doc_{project_name}_all_links.csv - все ссылки")
    print(f"✓ osnovateli_doc_{project_name}_image_links.csv - ссылки на изображения")
    print(f"✓ osnovateli_doc_{project_name}_youtube_links.csv - YouTube ссылки")
    print(f"✓ osnovateli_doc_{project_name}_video_links.csv - другие видео")
    print(f"✓ osnovateli_doc_{project_name}_other_links.csv - остальные ссылки")

if __name__ == "__main__":
    main()
