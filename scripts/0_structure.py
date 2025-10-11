import os
import re

def get_project_name():
    """Запрашивает название проекта и проверяет его формат"""
    while True:
        name = input('Введите название проекта: ').strip()
        if not name:
            print('Ошибка: название проекта не может быть пустым.')
            continue
        
        # Проверяем формат osnovateli_doc_{name}
        pattern = r'^osnovateli_doc_[a-zA-Z0-9_]+$'
        if not re.match(pattern, name):
            print('Ошибка: название должно соответствовать формату osnovateli_doc_{name}')
            print('Пример: osnovateli_doc_polonsky')
            continue
        
        return name

def get_required_structure():
    """Читает требуемую структуру из файла"""
    structure_file = '/Users/theseus/Projects/osnovateli_doc_framework/scripts/default_project_structure.txt'
    try:
        with open(structure_file, 'r', encoding='utf-8') as f:
            structure_lines = f.readlines()
    except FileNotFoundError:
        print(f'Ошибка: файл {structure_file} не найден')
        return None
    
    required_folders = []
    for line in structure_lines:
        folder_name = line.strip()
        if folder_name and not folder_name.startswith('#'):  # Пропускаем пустые строки и комментарии
            required_folders.append(folder_name)
    
    return required_folders

def check_existing_structure(project_dir):
    """Проверяет существующую структуру проекта"""
    if not os.path.exists(project_dir):
        return [], []
    
    existing_folders = []
    folders_with_files = []
    
    for item in os.listdir(project_dir):
        item_path = os.path.join(project_dir, item)
        if os.path.isdir(item_path):
            existing_folders.append(item)
            # Проверяем, есть ли файлы в папке
            try:
                files_in_folder = [f for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f))]
                if files_in_folder:
                    folders_with_files.append(item)
            except PermissionError:
                print(f'⚠️  Нет доступа к папке: {item}')
    
    return existing_folders, folders_with_files

def create_project_structure(project_name):
    """Создает или проверяет структуру папок для проекта"""
    # Путь к директории data
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    
    # Получаем требуемую структуру
    required_folders = get_required_structure()
    if required_folders is None:
        return False
    
    # Проверяем существующую структуру
    existing_folders, folders_with_files = check_existing_structure(project_dir)
    
    # Создаем директорию проекта, если её нет
    if not os.path.exists(project_dir):
        os.makedirs(project_dir, exist_ok=True)
        print(f'✓ Создана директория проекта: {project_dir}')
        existing_folders = []
        folders_with_files = []
    
    # Определяем недостающие папки
    missing_folders = [folder for folder in required_folders if folder not in existing_folders]
    
    # Определяем папки, которые есть в структуре, но отсутствуют в проекте
    extra_folders = [folder for folder in existing_folders if folder not in required_folders]
    
    # Создаем недостающие папки
    created_folders = []
    for folder_name in missing_folders:
        folder_path = os.path.join(project_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        created_folders.append(folder_name)
        print(f'✓ Создана папка: {folder_name}')
    
    # Выводим результаты
    print(f'\n=== РЕЗУЛЬТАТ ПРОВЕРКИ СТРУКТУРЫ ===')
    print(f'Проект: {project_name}')
    print(f'Директория: {project_dir}')
    
    if created_folders:
        print(f'✓ Создано новых папок: {len(created_folders)}')
        print(f'  Новые папки: {", ".join(created_folders)}')
    else:
        print('✓ Все требуемые папки уже существуют')
    
    if existing_folders:
        print(f'✓ Существующие папки: {len(existing_folders)}')
        print(f'  Папки: {", ".join(existing_folders)}')
    
    if folders_with_files:
        print(f'✓ Папки с файлами (не трогали): {len(folders_with_files)}')
        print(f'  Папки с содержимым: {", ".join(folders_with_files)}')
    
    if extra_folders:
        print(f'⚠️  Дополнительные папки (не в структуре): {len(extra_folders)}')
        print(f'  Дополнительные: {", ".join(extra_folders)}')
    
    return True

def main():
    print("=== СКРИПТ СОЗДАНИЯ СТРУКТУРЫ ПРОЕКТА ===")
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Создаем структуру
    success = create_project_structure(project_name)
    
    if success:
        print(f'\n✓ Структура проекта {project_name} успешно создана!')
    else:
        print(f'\n✗ Не удалось создать структуру проекта {project_name}')

if __name__ == "__main__":
    main()
