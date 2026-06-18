#!/usr/bin/env python3
"""
Создает или дополняет структуру папок проекта на основе default_project_structure.txt.
"""

from path_utils import get_data_dir, get_structure_file, resolve_project_name


def load_required_folders() -> list[str]:
    structure_file = get_structure_file(__file__)
    if not structure_file.exists():
        raise FileNotFoundError(f"Файл структуры не найден: {structure_file}")

    folders: list[str] = []
    for line in structure_file.read_text(encoding="utf-8").splitlines():
        folder_name = line.strip()
        if folder_name and not folder_name.startswith("#"):
            folders.append(folder_name)
    return folders


def main() -> None:
    print("=== OSNOVATELI.DOC FRAMEWORK ===")
    print("\n=== Stage1. Start! Создание структуры проекта ===")

    project_name = resolve_project_name()
    data_dir = get_data_dir(__file__)
    project_dir = data_dir / project_name

    required_folders = load_required_folders()

    project_dir.mkdir(parents=True, exist_ok=True)

    created_folders: list[str] = []
    existing_folders: list[str] = []

    for folder_name in required_folders:
        folder_path = project_dir / folder_name
        if folder_path.exists():
            existing_folders.append(folder_name)
            continue
        folder_path.mkdir(parents=True, exist_ok=True)
        created_folders.append(folder_name)

    if created_folders:
        print(f"Создана директория проекта: {project_dir}")
        print(f"Добавлено папок: {len(created_folders)}")
    else:
        print(f"Проект уже существует, структура актуальна: {project_dir}")

    print("=== Stage1. Done! Структура проекта готова ===")


if __name__ == "__main__":
    main()
