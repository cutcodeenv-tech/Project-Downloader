#!/usr/bin/env python3
"""
Скрипт для анализа файлов ошибок и группировки ссылок по индексам.
Автоматически находит файлы ошибок в директориях скриптов download_all и download_youtube.
Работает только с файлами текущей даты.
Результаты сохраняются в ~/Downloads/sort_errors/
"""

import os
import re
import glob
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def get_current_date():
    """
    Возвращает текущую дату в формате, используемом в именах файлов.
    
    Returns:
        str: Текущая дата в формате YYYY-MM-DD
    """
    return datetime.now().strftime('%Y-%m-%d')


def find_error_files():
    """
    Автоматически находит файлы ошибок в директориях скриптов.
    
    Returns:
        tuple: (parse_errors_file, youtube_errors_file) или (None, None) если файлы не найдены
    """
    current_date = get_current_date()
    
    # Пути к директориям, где сохраняются файлы ошибок
    parse_error_dir = os.path.expanduser('~/Downloads/media_from_sheet/*/parse_error')
    youtube_error_dir = os.path.expanduser('~/Downloads/youtube_videos/*/download_errors')
    
    # Ищем файлы parse errors
    parse_pattern = f'all_parse_errors_{current_date}_*.txt'
    parse_files = glob.glob(os.path.join(parse_error_dir, parse_pattern))
    
    # Ищем файлы youtube errors
    youtube_pattern = f'all_youtube_errors_{current_date}_*.txt'
    youtube_files = glob.glob(os.path.join(youtube_error_dir, youtube_pattern))
    
    # Выбираем самые свежие файлы (с самой поздней датой-временем)
    parse_file = max(parse_files) if parse_files else None
    youtube_file = max(youtube_files) if youtube_files else None
    
    return parse_file, youtube_file


def extract_links_with_names_from_file(file_path):
    """
    Извлекает ссылки с их названиями из файла ошибок.
    
    Args:
        file_path (str): Путь к файлу
    
    Returns:
        dict: Словарь {название: ссылка}
    """
    links_with_names = {}
    
    if not file_path or not os.path.isfile(file_path):
        return links_with_names
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line:
                    # Ищем ссылки в строке
                    url_pattern = r'https?://[^\s]+'
                    found_urls = re.findall(url_pattern, line)
                    
                    # Извлекаем название ссылки (B1, B2 и т.д.)
                    # Паттерн для поиска названия: B1 [1]: или B1: или просто B1
                    name_pattern = r'([A-Z]\d+)(?:\s*\[\d+\])?\s*:'
                    name_match = re.search(name_pattern, line)
                    
                    if name_match and found_urls:
                        name = name_match.group(1)
                        for url in found_urls:
                            links_with_names[name] = url
                    elif found_urls:
                        # Если название не найдено, используем URL как ключ
                        for url in found_urls:
                            links_with_names[url] = url
    except Exception as e:
        print(f"Ошибка при чтении файла {file_path}: {e}")
    
    return links_with_names


def extract_links_from_file(file_path):
    """
    Извлекает ссылки из файла ошибок (для обратной совместимости).
    
    Args:
        file_path (str): Путь к файлу
    
    Returns:
        set: Множество ссылок
    """
    links_with_names = extract_links_with_names_from_file(file_path)
    return set(links_with_names.values())


def extract_index_from_url(url):
    """
    Извлекает индекс B1-B из URL.
    
    Args:
        url (str): URL для анализа
    
    Returns:
        str: Индекс или None
    """
    # Ищем паттерн B1-B с номером
    index_pattern = r'B[1-9]\-B\d+'
    match = re.search(index_pattern, url)
    return match.group() if match else None


def group_links_by_name(links_with_names):
    """
    Группирует ссылки по их названиям (B1, B2 и т.д.).
    
    Args:
        links_with_names (dict): Словарь {название: ссылка}
    
    Returns:
        dict: Словарь с группированными ссылками по названиям
    """
    grouped_links = defaultdict(list)
    
    for name, link in links_with_names.items():
        # Извлекаем B-индекс из названия (B1, B2 и т.д.)
        name_match = re.match(r'([A-Z]\d+)', name)
        if name_match:
            group_name = name_match.group(1)
            grouped_links[group_name].append((name, link))
        else:
            # Если название не соответствует паттерну, помещаем в группу "Без индекса"
            grouped_links["Без индекса"].append((name, link))
    
    return grouped_links


def group_links_by_index(links):
    """
    Группирует ссылки по индексам B1-B (для обратной совместимости).
    
    Args:
        links (set): Множество ссылок
    
    Returns:
        dict: Словарь с группированными ссылками по индексам
    """
    grouped_links = defaultdict(list)
    
    for link in links:
        index = extract_index_from_url(link)
        if index:
            grouped_links[index].append(link)
        else:
            # Если индекс не найден, помещаем в группу "Без индекса"
            grouped_links["Без индекса"].append(link)
    
    return grouped_links


def create_sort_errors_directory():
    """
    Создает директорию sort_errors в системной папке Downloads.
    
    Returns:
        str: Путь к директории sort_errors
    """
    downloads_dir = os.path.expanduser('~/Downloads')
    sort_errors_dir = os.path.join(downloads_dir, 'sort_errors')
    os.makedirs(sort_errors_dir, exist_ok=True)
    return sort_errors_dir


def save_analysis_results(parse_links_with_names, youtube_links_with_names, intersection_links, grouped_links_by_name, parse_file, youtube_file):
    """
    Сохраняет результаты анализа в файл.
    
    Args:
        parse_links_with_names (dict): Ссылки с названиями из файла parse errors
        youtube_links_with_names (dict): Ссылки с названиями из файла youtube errors
        intersection_links (set): Пересечение ссылок
        grouped_links_by_name (dict): Сгруппированные ссылки по названиям
        parse_file (str): Путь к файлу parse errors
        youtube_file (str): Путь к файлу youtube errors
    """
    sort_errors_dir = create_sort_errors_directory()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = os.path.join(sort_errors_dir, f"all_errors_{timestamp}.txt")
    
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write("АНАЛИЗ ФАЙЛОВ ОШИБОК\n")
        file.write("=" * 50 + "\n\n")
        
        # Информация о файлах
        file.write("ИСПОЛЬЗОВАННЫЕ ФАЙЛЫ:\n")
        file.write(f"Parse errors: {parse_file or 'НЕ НАЙДЕН'}\n")
        file.write(f"YouTube errors: {youtube_file or 'НЕ НАЙДЕН'}\n")
        file.write(f"Дата анализа: {get_current_date()}\n\n")
        
        # Статистика
        file.write("СТАТИСТИКА:\n")
        file.write(f"Всего ссылок в parse errors: {len(parse_links_with_names)}\n")
        file.write(f"Всего ссылок в youtube errors: {len(youtube_links_with_names)}\n")
        file.write(f"Пересечение ссылок: {len(intersection_links)}\n")
        file.write(f"Уникальных групп по названиям: {len(grouped_links_by_name)}\n\n")
        
        # Пересечение ссылок
        if intersection_links:
            file.write("ПЕРЕСЕЧЕНИЕ ССЫЛОК:\n")
            file.write("-" * 30 + "\n")
            for link in sorted(intersection_links):
                file.write(f"{link}\n")
            file.write("\n")
        
        # Группировка по названиям (B1, B2 и т.д.)
        file.write("ГРУППИРОВКА ПО НАЗВАНИЯМ ССЫЛОК:\n")
        file.write("=" * 40 + "\n\n")
        
        # Собираем все ссылки в один список и сортируем по B-индексам
        all_sorted_links = []
        
        # Добавляем ссылки с B-индексами
        for group_name in sorted(grouped_links_by_name.keys(), key=lambda x: (x == "Без индекса", x)):
            if group_name != "Без индекса":
                links_in_group = grouped_links_by_name[group_name]
                all_sorted_links.extend(links_in_group)
        
        # Добавляем ссылки без индексов в конец
        if "Без индекса" in grouped_links_by_name:
            all_sorted_links.extend(grouped_links_by_name["Без индекса"])
        
        # Выводим все ссылки подряд в порядке увеличения B-индексов
        for name, link in all_sorted_links:
            file.write(f"{name}: {link}\n")
    
    print(f"Результаты сохранены в файл: {output_file}")
    return output_file


def main():
    """
    Основная функция скрипта.
    """
    print("Скрипт анализа файлов ошибок")
    print("=" * 40)
    
    # Проверяем текущую дату
    current_date = get_current_date()
    print(f"Текущая дата: {current_date}")
    print("Поиск файлов ошибок с текущей датой...")
    
    # Автоматически находим файлы ошибок
    parse_file, youtube_file = find_error_files()
    
    if not parse_file and not youtube_file:
        print("ОШИБКА: Не найдены файлы ошибок с текущей датой!")
        print("Убедитесь, что скрипты download_all и download_youtube были запущены сегодня.")
        return
    
    print(f"\nНайденные файлы:")
    if parse_file:
        print(f"Parse errors: {parse_file}")
    if youtube_file:
        print(f"YouTube errors: {youtube_file}")
    
    # Извлекаем ссылки с названиями из файлов
    print(f"\nАнализируем файлы...")
    parse_links_with_names = extract_links_with_names_from_file(parse_file)
    print(f"Найдено ссылок в parse errors: {len(parse_links_with_names)}")
    
    youtube_links_with_names = extract_links_with_names_from_file(youtube_file)
    print(f"Найдено ссылок в youtube errors: {len(youtube_links_with_names)}")
    
    # Находим пересечение ссылок
    parse_links_set = set(parse_links_with_names.values())
    youtube_links_set = set(youtube_links_with_names.values())
    intersection_links = parse_links_set & youtube_links_set
    print(f"Пересечение ссылок: {len(intersection_links)}")
    
    # Объединяем все ссылки с названиями для группировки
    all_links_with_names = {**parse_links_with_names, **youtube_links_with_names}
    print(f"Всего уникальных ссылок: {len(all_links_with_names)}")
    
    # Группируем ссылки по названиям (B1, B2 и т.д.)
    print("\nГруппируем ссылки по названиям...")
    grouped_links_by_name = group_links_by_name(all_links_with_names)
    
    # Выводим статистику группировки
    print(f"Найдено групп по названиям: {len(grouped_links_by_name)}")
    for group_name in sorted(grouped_links_by_name.keys(), key=lambda x: (x == "Без индекса", x)):
        links_count = len(grouped_links_by_name[group_name])
        print(f"  {group_name}: {links_count} ссылок")
    
    # Сохраняем результаты
    print("\nСохраняем результаты...")
    output_file = save_analysis_results(parse_links_with_names, youtube_links_with_names, intersection_links, grouped_links_by_name, parse_file, youtube_file)
    
    print(f"\nАнализ завершен! Результаты сохранены в: {output_file}")


if __name__ == "__main__":
    main() 