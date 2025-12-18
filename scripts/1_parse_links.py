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

def check_if_reparse(spreadsheet_url, database_dir):
    """
    Проверяет, парсилась ли данная ссылка ранее
    Возвращает True если это повторный парсинг, False если первый раз
    """
    input_link_file = os.path.join(database_dir, 'input_link.csv')
    
    if not os.path.exists(input_link_file):
        return False
    
    try:
        with open(input_link_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get('url') == spreadsheet_url:
                    return True
    except Exception as e:
        print(f"⚠️  Ошибка при чтении input_link.csv: {e}")
        return False
    
    return False

def save_input_link_info(spreadsheet_url, spreadsheet_id, database_dir, is_reparse):
    """
    Сохраняет информацию о парсимой ссылке в input_link.csv
    Записывает: URL таблицы, SPREADSHEET_ID, дату и время создания
    При первом запуске - создает файл, при повторном - добавляет строку
    """
    input_link_file = os.path.join(database_dir, 'input_link.csv')
    
    # Получаем текущую дату и время
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if is_reparse:
        # Добавляем новую запись в существующий файл
        with open(input_link_file, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([spreadsheet_url, spreadsheet_id, timestamp])
        print(f"✓ Обновлена информация о ссылке в: input_link.csv (повторный парсинг)")
    else:
        # Создаем новый файл
        with open(input_link_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['url', 'spreadsheet_id', 'created_at'])  # Заголовки
            writer.writerow([spreadsheet_url, spreadsheet_id, timestamp])
        print(f"✓ Информация о ссылке сохранена в: input_link.csv")
    
    print(f"  URL: {spreadsheet_url}")
    print(f"  ID: {spreadsheet_id}")
    print(f"  Дата: {timestamp}")

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
    Возвращает кортеж: (url, spreadsheet_id)
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
            return url, spreadsheet_id
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

def extract_links_from_csv_column_b(database_dir, gdoc_filename):
    """Извлекает ссылки из колонки B сохраненного CSV файла"""
    print(f"\n=== ПОИСК ССЫЛОК В КОЛОНКЕ B ===")
    
    input_gdoc_file = os.path.join(database_dir, gdoc_filename)
    
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

def is_motionarray_url(url):
    """Проверяет, является ли ссылка ссылкой на motionarray"""
    return 'motionarray.com' in url

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
    # Проверяем motionarray
    elif is_motionarray_url(url):
        return 'motionarray'
    # Затем проверяем изображения
    elif is_image_url(url):
        return 'image'
    # Затем проверяем видео (кроме YouTube и motionarray)
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

def save_table_structure_to_csv(spreadsheet_id, database_dir, is_reparse):
    """
    Сохраняет полную структуру таблицы в input_gdoc.csv
    При повторном парсинге создает файл с датой: input_gdoc_{dd-mm-yyyy}_{hh-mm}.csv
    """
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
    
    # Определяем имя файла
    if is_reparse:
        timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
        input_gdoc_file = os.path.join(database_dir, f'input_gdoc_{timestamp}.csv')
        print(f"⚠️  ПОВТОРНЫЙ ПАРСИНГ - создаем новую копию с датой")
    else:
        input_gdoc_file = os.path.join(database_dir, 'input_gdoc.csv')
    
    # Сохраняем в CSV
    with open(input_gdoc_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        for row in all_values:
            writer.writerow(row)
    
    filename = os.path.basename(input_gdoc_file)
    print(f"✓ Структура таблицы сохранена в: {filename}")
    print(f"✓ Строк в таблице: {len(all_values)}")
    return all_values, filename

def get_existing_urls_from_csv(filepath):
    """
    Читает существующие URL из CSV файла
    Возвращает set с URL (для быстрой проверки наличия)
    Игнорирует строки начинающиеся с 'upd_'
    """
    existing_urls = set()
    
    if not os.path.exists(filepath):
        return existing_urls
    
    try:
        with open(filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)  # Пропускаем заголовок
            
            for row in reader:
                if len(row) >= 2:
                    source_address = row[0]
                    url = row[1]
                    # Игнорируем строки upd_ и пустые URL
                    if not source_address.startswith('upd_') and url.strip():
                        existing_urls.add(url.strip())
    except Exception as e:
        print(f"⚠️  Ошибка при чтении существующих ссылок: {e}")
    
    return existing_urls

def filter_new_links(all_links, existing_urls):
    """
    Фильтрует список ссылок, оставляя только те, которых нет в existing_urls
    """
    new_links = []
    for link_info in all_links:
        if link_info['url'] not in existing_urls:
            new_links.append(link_info)
    return new_links

def save_links_to_csv(all_links, database_dir, project_name, is_reparse):
    """
    Сохраняет найденные ссылки в CSV файл
    При повторном парсинге добавляет строку upd_{dd-mm-yyyy}_{hh-mm} и дописывает только новые ссылки
    """
    if not all_links:
        print("Нет ссылок для сохранения")
        return
    
    all_links_file = os.path.join(database_dir, f'osnovateli_doc_{project_name}_all_links.csv')
    
    if is_reparse and os.path.exists(all_links_file):
        # Повторный парсинг - сравниваем с существующими ссылками
        existing_urls = get_existing_urls_from_csv(all_links_file)
        new_links = filter_new_links(all_links, existing_urls)
        
        if new_links:
            timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
            with open(all_links_file, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([f'upd_{timestamp}', ''])  # Строка-разделитель с датой
                for link_info in new_links:
                    writer.writerow([link_info['source_address'], link_info['url']])
            print(f"\n✓ Добавлено {len(new_links)} НОВЫХ ссылок в файл: osnovateli_doc_{project_name}_all_links.csv")
            print(f"  (после строки upd_{timestamp})")
            print(f"  Всего было найдено ссылок: {len(all_links)}, из них новых: {len(new_links)}")
        else:
            print(f"\n✓ Новых ссылок не обнаружено в файле: osnovateli_doc_{project_name}_all_links.csv")
            print(f"  Всего найдено ссылок: {len(all_links)}, все уже существуют")
    else:
        # Первый парсинг - создаем новый файл
        with open(all_links_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['source_address', 'url'])  # Заголовки
            for link_info in all_links:
                writer.writerow([link_info['source_address'], link_info['url']])
        print(f"\n✓ Сохранено {len(all_links)} ссылок в файл: osnovateli_doc_{project_name}_all_links.csv")

def categorize_links_from_csv(all_links, database_dir, project_name, is_reparse):
    """
    Категоризирует ссылки из CSV файла по типам и сохраняет в отдельные CSV
    При повторном парсинге добавляет строку upd_{dd-mm-yyyy}_{hh-mm} и дописывает только новые ссылки
    """
    print(f"\n=== КАТЕГОРИЗАЦИЯ ССЫЛОК ===")
    
    # Словари для группировки ссылок
    categorized_links = {
        'image': [],
        'youtube': [],
        'motionarray': [],
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
    timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M')
    
    for category, links in categorized_links.items():
        if links:
            filename = f"osnovateli_doc_{project_name}_{category}_links.csv"
            filepath = os.path.join(database_dir, filename)
            
            if is_reparse and os.path.exists(filepath):
                # Повторный парсинг - фильтруем только новые ссылки
                existing_urls = get_existing_urls_from_csv(filepath)
                new_links = filter_new_links(links, existing_urls)
                
                if new_links:
                    # Добавляем upd строку и дописываем только новые ссылки
                    with open(filepath, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([f'upd_{timestamp}', ''])  # Строка-разделитель с датой
                        for link_info in new_links:
                            writer.writerow([link_info['source_address'], link_info['url']])
                    print(f"\n✓ Добавлено {len(new_links)} НОВЫХ ссылок категории '{category}' в файл: {filename}")
                    print(f"  (после строки upd_{timestamp})")
                    print(f"  Всего найдено ссылок категории '{category}': {len(links)}, из них новых: {len(new_links)}")
                else:
                    print(f"\n✓ Новых ссылок категории '{category}' не обнаружено")
                    print(f"  Всего найдено ссылок: {len(links)}, все уже существуют")
            else:
                # Первый парсинг - создаем новый файл
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
    spreadsheet_url, spreadsheet_id = extract_spreadsheet_id_from_url()
    
    # Создаем структуру директорий в data/
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    
    # Создаем директории
    os.makedirs(database_dir, exist_ok=True)
    print(f"✓ Рабочая директория: {database_dir}")
    
    # Проверяем, повторный ли это парсинг
    is_reparse = check_if_reparse(spreadsheet_url, database_dir)
    
    if is_reparse:
        print(f"\n⚠️  ВНИМАНИЕ: Обнаружен повторный парсинг этой ссылки!")
        print(f"   Существующие данные будут сохранены")
        print(f"   Новые данные будут добавлены после строк upd_<дата>")
    else:
        print(f"\n✓ Первый парсинг этой ссылки")
    
    # Сохраняем информацию о ссылке
    save_input_link_info(spreadsheet_url, spreadsheet_id, database_dir, is_reparse)
    
    # Этап 1: Сохранение структуры таблицы
    table_structure, gdoc_filename = save_table_structure_to_csv(spreadsheet_id, database_dir, is_reparse)
    
    # Этап 2: Автоматический поиск ссылок в колонке B
    all_links = extract_links_from_csv_column_b(database_dir, gdoc_filename)
    
    # Этап 3: Сохранение всех ссылок в CSV
    save_links_to_csv(all_links, database_dir, project_name, is_reparse)
    
    # Этап 4: Категоризация ссылок
    categorized_links = categorize_links_from_csv(all_links, database_dir, project_name, is_reparse)
    
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Проект: {project_name}")
    print(f"Директория: {database_dir}")
    print(f"Режим: {'ПОВТОРНЫЙ ПАРСИНГ' if is_reparse else 'ПЕРВЫЙ ПАРСИНГ'}")
    print(f"Изображения: {len(categorized_links['image'])} ссылок")
    print(f"YouTube: {len(categorized_links['youtube'])} ссылок")
    print(f"MotionArray: {len(categorized_links['motionarray'])} ссылок")
    print(f"Видео (другие): {len(categorized_links['video'])} ссылок")
    print(f"Остальные: {len(categorized_links['other'])} ссылок")
    total_links = sum(len(links) for links in categorized_links.values())
    print(f"Всего: {total_links} ссылок")
    
    print(f"\n=== СОЗДАННЫЕ ФАЙЛЫ ===")
    if is_reparse:
        print(f"✓ {gdoc_filename} - новая копия структуры таблицы с датой")
        print(f"✓ osnovateli_doc_{project_name}_all_links.csv - обновлен (добавлены новые ссылки)")
        print(f"✓ osnovateli_doc_{project_name}_image_links.csv - обновлен (добавлены новые ссылки)")
        print(f"✓ osnovateli_doc_{project_name}_youtube_links.csv - обновлен (добавлены новые ссылки)")
        print(f"✓ osnovateli_doc_{project_name}_motionarray_links.csv - обновлен (добавлены новые ссылки)")
        print(f"✓ osnovateli_doc_{project_name}_video_links.csv - обновлен (добавлены новые ссылки)")
        print(f"✓ osnovateli_doc_{project_name}_other_links.csv - обновлен (добавлены новые ссылки)")
    else:
        print(f"✓ input_gdoc.csv - полная структура таблицы")
        print(f"✓ osnovateli_doc_{project_name}_all_links.csv - все ссылки")
        print(f"✓ osnovateli_doc_{project_name}_image_links.csv - ссылки на изображения")
        print(f"✓ osnovateli_doc_{project_name}_youtube_links.csv - YouTube ссылки")
        print(f"✓ osnovateli_doc_{project_name}_motionarray_links.csv - MotionArray ссылки")
        print(f"✓ osnovateli_doc_{project_name}_video_links.csv - другие видео")
        print(f"✓ osnovateli_doc_{project_name}_other_links.csv - остальные ссылки")

if __name__ == "__main__":
    main()
