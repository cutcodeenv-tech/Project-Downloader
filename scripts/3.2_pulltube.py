#!/usr/bin/env python3
"""
Скрипт для создания файла pulltube_links.txt из CSV файла с YouTube ссылками
"""

import os
import csv


def get_project_name():
    """Запрашивает название проекта у пользователя"""
    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("❌ Название проекта не может быть пустым!")


def main():
    """Основная функция скрипта"""
    print("=== СКРИПТ СОЗДАНИЯ ФАЙЛА ДЛЯ PULLTUBE ===")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Путь к CSV файлу с видео ссылками
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    csv_file = os.path.join(database_dir, f'osnovateli_doc_{project_name}_youtube_links.csv')
    
    if not os.path.exists(csv_file):
        print(f"❌ Файл {csv_file} не найден!")
        return
    
    # Читаем ссылки из CSV и создаем файл для pulltube
    pulltube_file = os.path.join(database_dir, 'pulltube_links.txt')
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as csv_f, \
             open(pulltube_file, 'w', encoding='utf-8') as txt_f:
            
            reader = csv.DictReader(csv_f)
            count = 0
            
            for row in reader:
                url = row.get('url', '').strip()
                if url:
                    txt_f.write(f"{url}\n")
                    count += 1
        
        print(f"✓ Создан файл pulltube_links.txt с {count} ссылками")
        print(f"📁 Файл сохранен в: {pulltube_file}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    main()
