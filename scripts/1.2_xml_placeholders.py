import gspread
from google.oauth2.service_account import Credentials
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import textwrap

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

def get_project_name():
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def calculate_font_size(text1, text2, text3):
    """
    Рассчитывает оптимальный размер шрифта исходя из объема текста
    """
    # Объединяем весь текст
    all_text = f"{text1} {text2} {text3}".strip()
    
    if not all_text:
        return 50  # Размер по умолчанию для пустого текста
    
    # Подсчитываем общее количество символов
    total_chars = len(all_text)
    
    # Базовые размеры для разных объемов текста
    if total_chars <= 100:
        return 60
    elif total_chars <= 300:
        return 50
    elif total_chars <= 600:
        return 40
    elif total_chars <= 1000:
        return 35
    elif total_chars <= 1500:
        return 30
    elif total_chars <= 2500:
        return 25
    else:
        return 20  # Минимальный размер для очень длинного текста

def create_text_image(text1, text2, text3, output_path):
    """
    Создает изображение 1920x1080 с тремя абзацами текста
    """
    # Рассчитываем оптимальный размер шрифта
    font_size = calculate_font_size(text1, text2, text3)
    
    # Создаем изображение
    width, height = 1920, 1080
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    # Пытаемся загрузить шрифт, если не получается - используем стандартный
    try:
        # Попытка загрузить системный шрифт
        font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
    except:
        try:
            # Попытка загрузить другой системный шрифт
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except:
            # Используем стандартный шрифт
            font = ImageFont.load_default()
    
    # Настройки текста
    text_color = (0, 0, 0)  # Черный цвет
    line_spacing = font_size * 1.2
    margin = 100
    max_width = width - 2 * margin
    
    # Функция для обертывания текста
    def wrap_text(text, max_width):
        if not text:
            return []
        # Примерное количество символов в строке
        chars_per_line = max_width // (font_size // 2)
        return textwrap.wrap(text, width=chars_per_line, break_long_words=False, break_on_hyphens=False)
    
    # Обрабатываем каждый абзац
    texts = [text1, text2, text3]
    current_y = margin
    
    for i, text in enumerate(texts):
        if text and text.strip():
            # Обертываем текст
            lines = wrap_text(text.strip(), max_width)
            
            # Рисуем каждую строку
            for line in lines:
                # Центрируем текст по горизонтали
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                x = (width - text_width) // 2
                
                draw.text((x, current_y), line, fill=text_color, font=font)
                current_y += line_spacing
            
            # Добавляем отступ между абзацами
            current_y += line_spacing * 0.5
    
    # Сохраняем изображение
    image.save(output_path, 'JPEG', quality=95)
    print(f"✓ Создано изображение: {output_path} (размер шрифта: {font_size})")

def read_table_data(spreadsheet_id):
    """
    Читает данные из Google таблицы
    """
    print(f"\n=== ЧТЕНИЕ ДАННЫХ ИЗ GOOGLE ТАБЛИЦЫ ===")
    
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
    
    # Получаем все данные из первых трех колонок
    all_values = worksheet.get_all_values()
    
    # Извлекаем данные из первых трех колонок
    rows_data = []
    for i, row in enumerate(all_values, 1):
        # Берем первые три колонки (A, B, C)
        col_a = row[0] if len(row) > 0 else ""
        col_b = row[1] if len(row) > 1 else ""
        col_c = row[2] if len(row) > 2 else ""
        
        # Если хотя бы одна колонка содержит данные, добавляем строку
        if col_a.strip() or col_b.strip() or col_c.strip():
            rows_data.append({
                'row_number': i,
                'col_a': col_a.strip(),
                'col_b': col_b.strip(),
                'col_c': col_c.strip()
            })
            print(f"Строка {i}: A='{col_a[:50]}...' B='{col_b[:50]}...' C='{col_c[:50]}...'")
    
    print(f"\n✓ Прочитано {len(rows_data)} строк с данными")
    return rows_data

def create_images_from_data(rows_data, output_dir):
    """
    Создает изображения из данных таблицы
    """
    print(f"\n=== СОЗДАНИЕ ИЗОБРАЖЕНИЙ ===")
    
    # Создаем выходную директорию
    os.makedirs(output_dir, exist_ok=True)
    
    created_count = 0
    
    for row_data in rows_data:
        row_number = row_data['row_number']
        col_a = row_data['col_a']
        col_b = row_data['col_b']
        col_c = row_data['col_c']
        
        # Создаем имя файла
        filename = f"{row_number}.jpg"
        output_path = os.path.join(output_dir, filename)
        
        # Создаем изображение
        create_text_image(col_a, col_b, col_c, output_path)
        created_count += 1
    
    print(f"\n✓ Создано {created_count} изображений в директории: {output_dir}")
    return created_count

def main():
    print("=== СКРИПТ СОЗДАНИЯ ИЗОБРАЖЕНИЙ С ТЕКСТОМ ИЗ GOOGLE ТАБЛИЦЫ ===")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Запрашиваем ссылку на таблицу
    spreadsheet_id = extract_spreadsheet_id_from_url()
    
    # Создаем структуру директорий
    downloads_dir = os.path.expanduser('~/Downloads')
    download_all_dir = os.path.join(downloads_dir, 'download_all')
    project_dir = os.path.join(download_all_dir, project_name)
    placeholders_dir = os.path.join(project_dir, '1.1_xml_placeholders')
    
    # Создаем директории
    os.makedirs(placeholders_dir, exist_ok=True)
    
    # Читаем данные из таблицы
    rows_data = read_table_data(spreadsheet_id)
    
    if not rows_data:
        print("Ошибка: в таблице не найдено данных для обработки.")
        return
    
    # Создаем изображения
    created_count = create_images_from_data(rows_data, placeholders_dir)
    
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Проект: {project_name}")
    print(f"Директория: {placeholders_dir}")
    print(f"Создано изображений: {created_count}")
    print(f"Размер изображений: 1920x1080")
    print(f"Размер шрифта: автоматический (зависит от объема текста)")

if __name__ == "__main__":
    main()
