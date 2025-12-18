#!/usr/bin/env python3
"""
Скрипт для создания файла pulltube_links.txt из CSV файла с YouTube ссылками
При наличии новых ссылок создает новый файл с датой/временем
"""

import os
import csv
from datetime import datetime


def get_project_name():
    """Запрашивает название проекта у пользователя"""
    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("❌ Название проекта не может быть пустым!")


def read_existing_links(pulltube_file):
    """Читает существующие ссылки из pulltube_links.txt"""
    if not os.path.exists(pulltube_file):
        return set()
    
    try:
        with open(pulltube_file, 'r', encoding='utf-8') as f:
            links = set(line.strip() for line in f if line.strip())
        return links
    except Exception as e:
        print(f"⚠️ Ошибка при чтении существующего файла: {e}")
        return set()


def read_csv_links(csv_file):
    """Читает все ссылки из CSV файла"""
    links = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as csv_f:
            reader = csv.DictReader(csv_f)
            for row in reader:
                url = row.get('url', '').strip()
                if url:
                    links.append(url)
        return links
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV: {e}")
        return []


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
    
    # Читаем ссылки из CSV
    csv_links = read_csv_links(csv_file)
    if not csv_links:
        print("❌ В CSV файле не найдено ссылок!")
        return
    
    print(f"📊 Всего ссылок в CSV: {len(csv_links)}")
    
    # Читаем существующие ссылки из pulltube_links.txt
    pulltube_file = os.path.join(database_dir, 'pulltube_links.txt')
    existing_links = read_existing_links(pulltube_file)
    
    if existing_links:
        print(f"📋 Существующих ссылок в pulltube_links.txt: {len(existing_links)}")
        
        # Находим новые ссылки
        csv_links_set = set(csv_links)
        new_links = csv_links_set - existing_links
        
        if not new_links:
            print("✓ Новых ссылок не обнаружено. Все ссылки уже есть в pulltube_links.txt")
            return
        
        print(f"🆕 Обнаружено новых ссылок: {len(new_links)}")
        
        # Создаем файл с датой и временем для новых ссылок
        now = datetime.now()
        timestamp = now.strftime("%d-%m-%Y_%H-%M")
        new_pulltube_file = os.path.join(database_dir, f'pulltube_links_{timestamp}.txt')
        
        try:
            with open(new_pulltube_file, 'w', encoding='utf-8') as f:
                # Записываем только новые ссылки
                for link in sorted(new_links):
                    f.write(f"{link}\n")
            
            print(f"✓ Создан новый файл с {len(new_links)} новыми ссылками")
            print(f"📁 Файл сохранен: {new_pulltube_file}")
            
        except Exception as e:
            print(f"❌ Ошибка при создании файла: {e}")
    
    else:
        # Первый запуск - создаем базовый файл pulltube_links.txt
        print("📝 Создаем первый файл pulltube_links.txt")
        
        try:
            with open(pulltube_file, 'w', encoding='utf-8') as f:
                for link in csv_links:
                    f.write(f"{link}\n")
            
            print(f"✓ Создан файл pulltube_links.txt с {len(csv_links)} ссылками")
            print(f"📁 Файл сохранен: {pulltube_file}")
            
        except Exception as e:
            print(f"❌ Ошибка при создании файла: {e}")


if __name__ == "__main__":
    main()
