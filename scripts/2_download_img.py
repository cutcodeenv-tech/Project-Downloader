import os
import requests
import re
from urllib.parse import urlparse
from datetime import datetime
import time
import subprocess
import sys

def extract_google_image_url(url):
    """Извлекает прямую ссылку на изображение из Google Images"""
    if 'share.google' not in url and 'images.app.goo.gl' not in url:
        return url
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        }
        
        print(f"  🔍 Извлекаю прямую ссылку из Google Images...")
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        if response.status_code == 200:
            print(f"  📍 Финальный URL после редиректа: {response.url}")
            
            # Ищем параметр imgurl в URL
            if 'imgurl=' in response.url:
                # Извлекаем imgurl параметр
                import urllib.parse
                parsed_url = urllib.parse.urlparse(response.url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                
                if 'imgurl' in query_params:
                    direct_url = query_params['imgurl'][0]
                    # Декодируем URL
                    direct_url = urllib.parse.unquote(direct_url)
                    print(f"  ✓ Найдена прямая ссылка: {direct_url}")
                    return direct_url
                else:
                    print(f"  ⚠️  Параметр imgurl не найден в URL")
            else:
                print(f"  ⚠️  Параметр imgurl не найден в URL")
            
            # Если не нашли imgurl, ищем в HTML
            html_content = response.text
            # Ищем ссылки на изображения в HTML
            import re
            img_patterns = [
                r'https://[^"\s]+\.(?:jpg|jpeg|png|gif|webp|bmp|tiff)',
                r'https://[^"\s]+\.(?:jpg|jpeg|png|gif|webp|bmp|tiff)\?[^"\s]*'
            ]
            
            for pattern in img_patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                if matches:
                    # Берем первую найденную ссылку на изображение
                    direct_url = matches[0]
                    print(f"  ✓ Найдена прямая ссылка в HTML: {direct_url}")
                    return direct_url
        
        print(f"  ⚠️  Не удалось извлечь прямую ссылку, используем оригинальную")
        return url
        
    except Exception as e:
        print(f"  ❌ Ошибка при извлечении прямой ссылки: {e}")
        return url

def check_and_install_dependencies():
    """Проверяет и устанавливает необходимые зависимости"""
    print("=== ПРОВЕРКА ЗАВИСИМОСТЕЙ ===")
    
    required_packages = {
        'requests': 'requests',
        'PIL': 'Pillow'
    }
    
    missing_packages = []
    
    for package_name, pip_name in required_packages.items():
        try:
            if package_name == 'PIL':
                import PIL
                print(f"✓ {package_name} уже установлен")
            else:
                __import__(package_name)
                print(f"✓ {package_name} уже установлен")
        except ImportError:
            missing_packages.append((package_name, pip_name))
            print(f"❌ {package_name} не найден")
    
    if missing_packages:
        print(f"\nУстанавливаю недостающие пакеты...")
        for package_name, pip_name in missing_packages:
            try:
                print(f"Устанавливаю {package_name}...")
                subprocess.check_call(['brew', 'install', 'python-' + pip_name])
                print(f"✓ {package_name} успешно установлен")
            except subprocess.CalledProcessError as e:
                print(f"❌ Ошибка при установке {package_name}: {e}")
                return False
    
    print("✓ Все зависимости готовы\n")
    return True

def convert_to_jpg(input_path, output_path):
    """Конвертирует изображение в JPG формат"""
    try:
        from PIL import Image
        
        # Открываем изображение
        with Image.open(input_path) as img:
            # Конвертируем в RGB если изображение в другом режиме (например, RGBA)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Создаем белый фон для прозрачных изображений
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Сохраняем в JPG с высоким качеством
            img.save(output_path, 'JPEG', quality=95, optimize=True)
        
        return True
    except Exception as e:
        print(f"  ❌ Ошибка конвертации: {e}")
        return False

def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def get_file_extension_from_url(url):
    """Извлекает расширение файла из URL"""
    parsed_url = urlparse(url)
    path = parsed_url.path
    
    # Ищем расширение в пути
    if '.' in path:
        extension = path.split('.')[-1].lower()
        # Проверяем, что это действительно расширение изображения
        if extension in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg']:
            return f'.{extension}'
    
    # Если расширение не найдено в пути, проверяем параметры
    if 'format=' in url:
        format_match = re.search(r'format=([^&]+)', url)
        if format_match:
            format_val = format_match.group(1).lower()
            if format_val in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                return f'.{format_val}'
    
    # По умолчанию возвращаем .jpg
    return '.jpg'

def get_file_extension_from_headers(url):
    """Определяет расширение файла по HTTP заголовкам"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            
            if 'image/jpeg' in content_type or 'image/jpg' in content_type:
                return '.jpg'
            elif 'image/png' in content_type:
                return '.png'
            elif 'image/gif' in content_type:
                return '.gif'
            elif 'image/webp' in content_type:
                return '.webp'
            elif 'image/bmp' in content_type:
                return '.bmp'
            elif 'image/tiff' in content_type:
                return '.tiff'
            elif 'image/svg+xml' in content_type:
                return '.svg'
        
        return None
    except Exception as e:
        print(f"Ошибка при проверке заголовков для {url}: {e}")
        return None

def sanitize_filename(filename):
    """Очищает имя файла от недопустимых символов"""
    # Заменяем недопустимые символы на подчеркивание
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Убираем лишние пробелы и подчеркивания
    filename = re.sub(r'\s+', '_', filename)
    filename = re.sub(r'_+', '_', filename)
    
    return filename.strip('_')

def download_image(url, filename, download_dir):
    """Скачивает изображение по URL и конвертирует в JPG"""
    try:
        # Извлекаем прямую ссылку для Google Images
        direct_url = extract_google_image_url(url)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        print(f"Скачиваю: {filename}")
        response = requests.get(direct_url, headers=headers, timeout=30, allow_redirects=True, stream=True)
        
        if response.status_code == 200:
            # Проверяем, что это действительно изображение
            content_type = response.headers.get('content-type', '').lower()
            if not content_type.startswith('image/'):
                print(f"  ⚠️  Предупреждение: {content_type} - не изображение")
            
            # Определяем расширение файла для временного сохранения
            extension = get_file_extension_from_headers(url)
            if not extension:
                extension = get_file_extension_from_url(url)
            
            # Используем имя файла из CSV как есть, без добавления индексов
            final_filepath = os.path.join(download_dir, f"{filename}.jpg")
            temp_filepath = os.path.join(download_dir, f"{filename}{extension}")
            
            # Сохраняем временный файл
            with open(temp_filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Конвертируем в JPG
            if extension.lower() == '.jpg':
                # Если уже JPG, просто переименовываем
                os.rename(temp_filepath, final_filepath)
                print(f"  ✓ Сохранено: {os.path.basename(final_filepath)}")
            else:
                # Конвертируем в JPG
                if convert_to_jpg(temp_filepath, final_filepath):
                    # Удаляем временный файл
                    os.remove(temp_filepath)
                    print(f"  ✓ Конвертировано и сохранено: {os.path.basename(final_filepath)}")
                else:
                    # Если конвертация не удалась, оставляем оригинальный файл
                    print(f"  ⚠️  Сохранено без конвертации: {os.path.basename(temp_filepath)}")
            
            return True
            
        else:
            print(f"  ❌ Ошибка HTTP: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"  ❌ Таймаут при скачивании")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Ошибка соединения")
        return False
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        return False

def get_existing_images(pictures_dir):
    """
    Получает список существующих изображений в директории
    Возвращает set с именами файлов (например, {'B3_1', 'B4_1', ...})
    """
    existing = set()
    
    if not os.path.exists(pictures_dir):
        return existing
    
    # Ищем все файлы .jpg в директории
    for filename in os.listdir(pictures_dir):
        if filename.endswith('.jpg'):
            # Извлекаем имя без расширения (например, "B3_1.jpg" -> "B3_1")
            name_without_ext = filename.replace('.jpg', '')
            existing.add(name_without_ext)
    
    return existing

def read_image_links_from_csv(project_name):
    """
    Читает ссылки на изображения из CSV файла проекта
    Игнорирует строки начинающиеся с 'upd_'
    """
    import csv
    
    print(f"\n=== ЧТЕНИЕ ССЫЛОК НА ИЗОБРАЖЕНИЯ ИЗ CSV ===")
    
    # Путь к CSV файлу с изображениями
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    csv_file = os.path.join(database_dir, f'osnovateli_doc_{project_name}_image_links.csv')
    
    if not os.path.exists(csv_file):
        print(f"❌ Файл {csv_file} не найден!")
        print("Сначала запустите скрипт 1_parse_links.py для создания CSV файла с изображениями.")
        return []
    
    links = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_address = row.get('source_address', '').strip()
                url = row.get('url', '').strip()
                
                # Игнорируем строки upd_ и пустые
                if source_address and url and not source_address.startswith('upd_'):
                    links.append({
                        'display_name': source_address,
                        'url': url
                    })
                    print(f"✓ Найдена ссылка: {source_address} -> {url[:50]}...")
        
        print(f"\n✓ Прочитано {len(links)} ссылок на изображения из {csv_file}")
        return links
        
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV файла {csv_file}: {e}")
        return []

def create_error_placeholder(display_name, download_dir):
    """Создает изображение-заглушку для неудачных скачиваний"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Создаем изображение 1920x1080 с белым фоном
        img = Image.new('RGB', (1920, 1080), color='white')
        draw = ImageDraw.Draw(img)
        
        # Пытаемся использовать системный шрифт, если не получится - используем стандартный
        try:
            # Пробуем найти подходящий шрифт
            font_size = 60
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except:
                font = ImageFont.load_default()
        
        # Текст для отображения
        text = f"download_error {display_name}"
        
        # Получаем размеры текста
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Вычисляем позицию для центрирования текста
        x = (1920 - text_width) // 2
        y = (1080 - text_height) // 2
        
        # Рисуем текст черным цветом
        draw.text((x, y), text, fill='black', font=font)
        
        # Сохраняем изображение с именем из CSV (без добавления индексов)
        filepath = os.path.join(download_dir, f"{display_name}.jpg")
        
        # Если файл уже существует, перезаписываем его
        img.save(filepath, 'JPEG', quality=95)
        print(f"  ✓ Создана заглушка: {os.path.basename(filepath)}")
        return True
        
    except Exception as e:
        print(f"  ❌ Ошибка создания заглушки: {e}")
        return False

def log_download_error(display_name, url, error_file_path, download_dir):
    """Логирует ошибки скачивания в CSV файл и создает заглушку"""
    import csv
    
    try:
        # Проверяем, существует ли файл (чтобы понять, нужно ли писать заголовки)
        file_exists = os.path.exists(error_file_path)
        
        with open(error_file_path, 'a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            
            # Если файл новый, пишем заголовки
            if not file_exists:
                writer.writerow(['source_address', 'url'])
            
            # Пишем данные об ошибке
            writer.writerow([display_name, url])
        
        # Создаем изображение-заглушку
        create_error_placeholder(display_name, download_dir)
        
    except Exception as e:
        print(f"Ошибка при записи в файл ошибок: {e}")

def main():
    print("=== СКРИПТ СКАЧИВАНИЯ ИЗОБРАЖЕНИЙ ===")
    
    # Проверяем и устанавливаем зависимости
    if not check_and_install_dependencies():
        print("❌ Не удалось установить необходимые зависимости!")
        return
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Проверяем, что проект существует
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    if not os.path.exists(project_dir):
        print(f"❌ Проект {project_name} не найден в {project_dir}")
        print("Сначала запустите скрипт 0_structure.py для создания структуры проекта")
        return
    
    # Создаем структуру директорий в проекте
    pictures_dir = os.path.join(project_dir, 'pictures')
    database_dir = os.path.join(project_dir, 'database')
    
    # Создаем директории
    os.makedirs(pictures_dir, exist_ok=True)
    os.makedirs(database_dir, exist_ok=True)
    
    # Путь к CSV файлу ошибок в директории database
    error_file_path = os.path.join(database_dir, f'osnovateli_doc_{project_name}_download_img_errors.csv')
    
    print(f"\n=== СКАЧИВАНИЕ ИЗОБРАЖЕНИЙ ===")
    print(f"Проект: {project_name}")
    print(f"Директория изображений: {pictures_dir}")
    print("Все изображения будут конвертированы в JPG формат")
    
    # Получаем список существующих изображений
    existing_images = get_existing_images(pictures_dir)
    
    if existing_images:
        print(f"\n✓ Найдено существующих изображений: {len(existing_images)}")
        print(f"  Примеры: {list(existing_images)[:5]}{'...' if len(existing_images) > 5 else ''}")
    else:
        print(f"\n✓ Существующих изображений не найдено")
    
    # Читаем ссылки на изображения из CSV файла
    image_links = read_image_links_from_csv(project_name)
    
    if not image_links:
        print("❌ Не найдено ссылок на изображения для скачивания!")
        return
    
    # Фильтруем ссылки - оставляем только те, для которых нет изображений
    links_to_download = []
    skipped_count = 0
    
    for link_info in image_links:
        if link_info['display_name'] in existing_images:
            skipped_count += 1
        else:
            links_to_download.append(link_info)
    
    print(f"\nВсего ссылок в CSV: {len(image_links)}")
    print(f"Существующих изображений: {skipped_count}")
    print(f"Нужно скачать: {len(links_to_download)}")
    
    if not links_to_download:
        print("\n✓ Все изображения уже скачаны! Нечего делать.")
        return
    
    # Скачиваем только новые изображения
    successful_downloads = 0
    failed_downloads = 0
    
    for i, link_info in enumerate(links_to_download, 1):
        print(f"\n[{i}/{len(links_to_download)}] Обрабатываю: {link_info['display_name']}")
        
        if download_image(link_info['url'], link_info['display_name'], pictures_dir):
            successful_downloads += 1
        else:
            failed_downloads += 1
            log_download_error(link_info['display_name'], link_info['url'], error_file_path, pictures_dir)
        
        # Небольшая пауза между запросами
        time.sleep(0.5)
    
    print(f"\n=== РЕЗУЛЬТАТЫ СКАЧИВАНИЯ ===")
    print(f"Успешно скачано и конвертировано: {successful_downloads}")
    print(f"Ошибок скачивания: {failed_downloads}")
    print(f"Пропущено (уже существуют): {skipped_count}")
    print(f"Всего ссылок в CSV: {len(image_links)}")
    print(f"Всего изображений в директории: {len(existing_images) + successful_downloads}")
    
    if failed_downloads > 0:
        print(f"\n⚠️  Ошибки сохранены в CSV файл: {error_file_path}")
        print(f"   (Созданы заглушки для неудачных скачиваний)")
    
    print(f"\n✓ Изображения сохранены в JPG формате в: {pictures_dir}")

if __name__ == "__main__":
    main()
