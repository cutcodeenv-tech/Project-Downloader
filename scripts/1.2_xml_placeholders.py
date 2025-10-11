import os
import re
import csv
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import textwrap

def read_csv_data(project_name):
    """
    Читает данные из input_gdoc.csv файла проекта
    """
    print(f"\n=== ЧТЕНИЕ ДАННЫХ ИЗ CSV ФАЙЛА ===")
    
    # Путь к CSV файлу
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    csv_file = os.path.join(database_dir, 'input_gdoc.csv')
    
    if not os.path.exists(csv_file):
        print(f"Ошибка: файл {csv_file} не найден.")
        print("Сначала запустите скрипт 1_parse_links.py для создания CSV файла.")
        return []
    
    rows_data = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            csv_rows = list(reader)
            
            for i, row in enumerate(csv_rows, 1):
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
        
        print(f"\n✓ Прочитано {len(rows_data)} строк с данными из {csv_file}")
        return rows_data
        
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}")
        return []

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

def remove_links_from_text(text):
    """
    Удаляет ссылки из текста, оставляя только текст
    """
    if not text:
        return text
    
    # Паттерн для поиска ссылок (http/https)
    url_pattern = r'https?://[^\s]+'
    # Удаляем ссылки
    text_without_links = re.sub(url_pattern, '', text)
    # Убираем лишние пробелы
    return ' '.join(text_without_links.split())

def create_text_image(text1, text2, text3, row_number, output_path):
    """
    Создает изображение 1920x1080 с тремя абзацами текста с подписями и номером строки
    """
    # Рассчитываем оптимальный размер шрифта
    font_size = calculate_font_size(text1, text2, text3)
    
    # Создаем изображение
    width, height = 1920, 1080
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    # Пытаемся загрузить шрифт из assets/font, если не получается - используем системные
    try:
        # Попытка загрузить шрифт из проекта
        project_font_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/font/theater.bold-condensed.ttf"
        font = ImageFont.truetype(project_font_path, font_size)
        label_font = ImageFont.truetype(project_font_path, font_size + 10)
        index_font = ImageFont.truetype(project_font_path, font_size + 20)
        print(f"✓ Используется шрифт проекта: theater.bold-condensed.ttf")
    except:
        try:
            # Попытка загрузить системный шрифт
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
            label_font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size + 10)
            index_font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size + 20)
            print("✓ Используется системный шрифт: Arial")
        except:
            try:
                # Попытка загрузить другой системный шрифт
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
                label_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size + 10)
                index_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size + 20)
                print("✓ Используется системный шрифт: Helvetica")
            except:
                # Используем стандартный шрифт
                font = ImageFont.load_default()
                label_font = ImageFont.load_default()
                index_font = ImageFont.load_default()
                print("✓ Используется стандартный шрифт")
    
    # Настройки текста
    text_color = (0, 0, 0)  # Черный цвет
    label_color = (100, 100, 100)  # Серый цвет для подписей
    index_color = (50, 50, 50)  # Темно-серый цвет для номера строки
    line_spacing = font_size * 1.2
    margin = 100
    max_width = width - 2 * margin
    
    # Рисуем номер строки в правом верхнем углу
    index_text = f"#{row_number}"
    bbox = draw.textbbox((0, 0), index_text, font=index_font)
    index_width = bbox[2] - bbox[0]
    index_x = width - margin - index_width
    index_y = margin
    
    draw.text((index_x, index_y), index_text, fill=index_color, font=index_font)
    
    # Функция для обертывания текста
    def wrap_text(text, max_width):
        if not text:
            return []
        # Примерное количество символов в строке
        chars_per_line = max_width // (font_size // 2)
        return textwrap.wrap(text, width=chars_per_line, break_long_words=False, break_on_hyphens=False)
    
    # Обрабатываем каждый абзац с подписями
    texts_and_labels = [
        (text1, "voiceover"),
        (remove_links_from_text(text2), "storyboard"),  # Удаляем ссылки из второй колонки
        (text3, "mogrt")
    ]
    current_y = margin + font_size + 30  # Отступ от номера строки
    
    for text, label in texts_and_labels:
        if text and text.strip():
            # Рисуем подпись
            draw.text((margin, current_y), label.upper(), fill=label_color, font=label_font)
            current_y += line_spacing * 1.5
            
            # Обертываем текст
            lines = wrap_text(text.strip(), max_width)
            
            # Рисуем каждую строку (выравнивание по левому краю)
            for line in lines:
                draw.text((margin, current_y), line, fill=text_color, font=font)
                current_y += line_spacing
            
            # Добавляем отступ между абзацами
            current_y += line_spacing * 0.8
    
    # Сохраняем изображение
    image.save(output_path, 'JPEG', quality=95)
    print(f"✓ Создано изображение: {output_path} (строка #{row_number}, размер шрифта: {font_size})")


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
        create_text_image(col_a, col_b, col_c, row_number, output_path)
        created_count += 1
    
    print(f"\n✓ Создано {created_count} изображений в директории: {output_dir}")
    return created_count

def main():
    print("=== СКРИПТ СОЗДАНИЯ ИЗОБРАЖЕНИЙ С ТЕКСТОМ ИЗ CSV ФАЙЛА ===")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Проверяем, что проект существует
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    if not os.path.exists(project_dir):
        print(f"Ошибка: проект {project_name} не найден в {project_dir}")
        print("Сначала запустите скрипт 0_structure.py для создания структуры проекта")
        return
    
    # Создаем структуру директорий в проекте
    placeholders_dir = os.path.join(project_dir, 'xml_placeholders')
    
    # Создаем директории
    os.makedirs(placeholders_dir, exist_ok=True)
    
    # Читаем данные из CSV файла
    rows_data = read_csv_data(project_name)
    
    if not rows_data:
        print("Ошибка: в CSV файле не найдено данных для обработки.")
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
