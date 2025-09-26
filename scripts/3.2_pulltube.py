#!/usr/bin/env python3
"""
Скрипт для создания файла pulltube_links.txt из youtube_links.txt
Извлекает все ссылки на YouTube видео и сохраняет их в формате для pulltube.com
"""

import os
import re
from pathlib import Path
from datetime import datetime


def get_project_name():
    """Запрашивает название проекта у пользователя"""
    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("❌ Название проекта не может быть пустым!")


def is_youtube_url(url):
    """Проверяет, является ли ссылка YouTube ссылкой"""
    youtube_patterns = [
        r'youtube\.com',
        r'youtu\.be',
        r'youtube-nocookie\.com'
    ]
    
    for pattern in youtube_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def read_youtube_links(youtube_links_file):
    """Читает ссылки на YouTube видео из файла youtube_links.txt"""
    links = []
    
    try:
        if not os.path.exists(youtube_links_file):
            print(f"❌ Файл {youtube_links_file} не найден!")
            return links
        
        with open(youtube_links_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            
            # Парсим строку формата "A1 1 : https://youtube.com/..."
            parts = line.split(' : ', 1)
            if len(parts) == 2:
                display_name = parts[0].strip()
                url = parts[1].strip()
                
                # Проверяем, что это YouTube ссылка
                if is_youtube_url(url):
                    links.append({
                        'display_name': display_name,
                        'url': url,
                        'line_number': line_num
                    })
                    print(f"✓ Найдена ссылка: {display_name} -> {url}")
                else:
                    print(f"⚠️  Пропускаю не-YouTube ссылку (строка {line_num}): {url}")
            else:
                print(f"⚠️  Неверный формат строки {line_num}: {line}")
        
        return links
        
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {youtube_links_file}: {e}")
        return []


def create_pulltube_file(youtube_links, output_dir):
    """Создает файл pulltube_links.txt для использования на pulltube.com"""
    try:
        pulltube_file = os.path.join(output_dir, 'pulltube_links.txt')
        
        with open(pulltube_file, 'w', encoding='utf-8') as f:
            for link_info in youtube_links:
                f.write(f"{link_info['url']}\n")
        
        print(f"✓ Создан файл pulltube_links.txt с {len(youtube_links)} ссылками")
        print(f"📁 Файл сохранен в: {pulltube_file}")
        
        return pulltube_file
        
    except Exception as e:
        print(f"❌ Ошибка при создании файла pulltube_links.txt: {e}")
        return None


def create_detailed_report(youtube_links, output_dir):
    """Создает детальный отчет о ссылках"""
    try:
        report_file = os.path.join(output_dir, 'pulltube_report.txt')
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("ОТЧЕТ ПО ССЫЛКАМ ДЛЯ PULLTUBE\n")
            f.write("=" * 40 + "\n\n")
            f.write(f"Дата создания: {timestamp}\n")
            f.write(f"Всего ссылок: {len(youtube_links)}\n\n")
            
            f.write("ДЕТАЛЬНЫЙ СПИСОК:\n")
            f.write("-" * 30 + "\n")
            
            for i, link_info in enumerate(youtube_links, 1):
                f.write(f"{i:3d}. {link_info['display_name']}\n")
                f.write(f"     URL: {link_info['url']}\n")
                f.write(f"     Строка в исходном файле: {link_info['line_number']}\n")
                f.write("\n")
        
        print(f"✓ Создан детальный отчет: {report_file}")
        return report_file
        
    except Exception as e:
        print(f"❌ Ошибка при создании отчета: {e}")
        return None


def main():
    """Основная функция скрипта"""
    print("=== СКРИПТ СОЗДАНИЯ ФАЙЛА ДЛЯ PULLTUBE ===")
    print("=" * 45)
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Создаем структуру директорий
    downloads_dir = os.path.expanduser('~/Downloads')
    download_all_dir = os.path.join(downloads_dir, 'download_all')
    project_dir = os.path.join(download_all_dir, project_name)
    parse_links_dir = os.path.join(project_dir, '1_parse_links')
    pulltube_dir = os.path.join(project_dir, '3.2_pulltube')
    
    # Проверяем существование директории с ссылками
    if not os.path.exists(parse_links_dir):
        print(f"❌ Директория {parse_links_dir} не найдена!")
        print("Сначала запустите скрипт 1_parse_links.py")
        return
    
    # Создаем директорию для pulltube файлов
    os.makedirs(pulltube_dir, exist_ok=True)
    
    # Путь к файлу с ссылками на YouTube видео
    youtube_links_file = os.path.join(parse_links_dir, 'youtube_links.txt')
    
    print(f"\nПроект: {project_name}")
    print(f"Директория pulltube: {pulltube_dir}")
    print(f"Файл с ссылками: {youtube_links_file}")
    
    # Читаем ссылки на YouTube видео
    print(f"\nЧитаю ссылки из файла...")
    youtube_links = read_youtube_links(youtube_links_file)
    
    if not youtube_links:
        print("❌ Не найдено ссылок на YouTube видео!")
        return
    
    print(f"\nНайдено {len(youtube_links)} ссылок на YouTube видео")
    
    # Создаем файл для pulltube
    print(f"\nСоздаю файл для pulltube...")
    pulltube_file = create_pulltube_file(youtube_links, pulltube_dir)
    
    if not pulltube_file:
        print("❌ Не удалось создать файл для pulltube!")
        return
    
    # Создаем детальный отчет
    print(f"\nСоздаю детальный отчет...")
    report_file = create_detailed_report(youtube_links, pulltube_dir)
    
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✓ Обработано ссылок: {len(youtube_links)}")
    print(f"✓ Файл для pulltube: {pulltube_file}")
    if report_file:
        print(f"✓ Детальный отчет: {report_file}")
    
    print(f"\nТеперь вы можете:")
    print(f"1. Открыть файл {pulltube_file}")
    print(f"2. Скопировать все ссылки")
    print(f"3. Вставить их на сайт pulltube.com для скачивания")


if __name__ == "__main__":
    main()
