#!/usr/bin/env python3
"""
Скрипт для упаковки JPG фотографий в MOV композиции с альфа каналом при помощи ffmpeg
"""

import os
import subprocess
import sys
from PIL import Image
import glob

def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def get_existing_video_placeholders(output_dir):
    """
    Получает список существующих видео-плейсхолдеров в выходной директории
    Возвращает set с именами файлов без расширения (например, {'B3_1', 'B4_1', ...})
    """
    existing = set()
    
    if not os.path.exists(output_dir):
        return existing
    
    # Ищем все файлы .mov в директории
    for filename in os.listdir(output_dir):
        if filename.endswith('.mov') and os.path.isfile(os.path.join(output_dir, filename)):
            # Извлекаем имя без расширения (например, "B3_1.mov" -> "B3_1")
            name_without_ext = os.path.splitext(filename)[0]
            existing.add(name_without_ext)
    
    return existing

def check_ffmpeg():
    """Проверяет наличие ffmpeg в системе"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✓ ffmpeg найден")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ffmpeg не найден! Установите ffmpeg для работы скрипта")
        print("Установка через Homebrew: brew install ffmpeg")
        return False

def check_image_aspect_ratio(image_path):
    """Проверяет, что изображение имеет соотношение сторон 16:9"""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            aspect_ratio = width / height
            target_ratio = 16 / 9
            
            # Допускаем небольшую погрешность (0.01)
            if abs(aspect_ratio - target_ratio) <= 0.01:
                print(f"  ✓ Соотношение сторон 16:9 ({width}x{height})")
                return True
            else:
                print(f"  ❌ Неверное соотношение сторон: {width}x{height} (ожидается 16:9)")
                return False
    except Exception as e:
        print(f"  ❌ Ошибка при проверке изображения: {e}")
        return False

def create_video_placeholder(image_path, output_path, scratches_path, alpha_mask_path):
    """Создает MOV видео с наложением белых царапин и альфа-маски из JPG изображения"""
    try:
        # Команда ffmpeg для создания видео с наложением царапин через маску
        cmd = [
            'ffmpeg',
            '-y',  # Перезаписать выходной файл
            '-loop', '1',  # Зациклить изображение
            '-i', image_path,  # Входное изображение
            '-i', scratches_path,  # Файл с царапинами
            '-i', alpha_mask_path,  # Альфа-маска
            '-filter_complex', 
            # Масштабируем и центрируем основное изображение
            f'[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[bg];'
            # Инвертируем цвета царапин (черные становятся белыми) и удаляем белый фон
            f'[1:v]negate,colorkey=white:0.1:0.0[scratches_transparent];'
            # Композируем царапины поверх основного изображения
            f'[bg][scratches_transparent]overlay=0:0[with_scratches];'
            # Инвертируем альфа-маску (прозрачные области становятся непрозрачными)
            f'[2:v]negate[inverted_alpha];'
            # Применяем инвертированную альфа-маску к результату
            f'[with_scratches][inverted_alpha]alphamerge[final]',
            '-map', '[final]',
            '-c:v', 'prores_ks',  # Кодек ProRes 4444
            '-profile:v', '4444',  # Профиль ProRes 4444 с альфа-каналом
            '-pix_fmt', 'yuva444p10le',  # Пиксельный формат с альфа-каналом
            '-r', '25',  # Частота кадров
            '-t', '10',  # Длительность 10 секунд
            output_path
        ]
        
        print(f"  🎬 Создаю видео: {os.path.basename(output_path)} (царапины + альфа-маска, ProRes 4444)")
        
        # Выполняем команду ffmpeg
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"  ✓ Видео создано успешно")
            return True
        else:
            print(f"  ❌ Ошибка ffmpeg: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"  ❌ Ошибка при создании видео: {e}")
        return False

def main():
    print("=== СКРИПТ СОЗДАНИЯ PHOTO PLACEHOLDERS ===")
    
    # Получаем название проекта
    project_name = get_project_name()
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        return
    
    # Пути к директориям и файлам
    base_path = "/Users/theseus/Projects/osnovateli_doc_framework/data"
    input_dir = os.path.join(base_path, project_name, "smart_cropped_pictures")
    output_dir = os.path.join(base_path, project_name, "photo_placeholder")
    scratches_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/scratches_add.mp4"
    alpha_mask_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/alpha_mask.mp4"
    
    # Проверяем существование входной директории
    if not os.path.exists(input_dir):
        print(f"❌ Входная директория не найдена: {input_dir}")
        return
    
    # Проверяем существование файла с царапинами
    if not os.path.exists(scratches_path):
        print(f"❌ Файл с царапинами не найден: {scratches_path}")
        return
    
    # Проверяем существование файла альфа-маски
    if not os.path.exists(alpha_mask_path):
        print(f"❌ Файл альфа-маски не найден: {alpha_mask_path}")
        return
    
    # Создаем выходную директорию
    os.makedirs(output_dir, exist_ok=True)
    
    # Ищем все JPG файлы в входной директории
    jpg_files = glob.glob(os.path.join(input_dir, "*.jpg"))
    jpg_files.extend(glob.glob(os.path.join(input_dir, "*.jpeg")))
    
    if not jpg_files:
        print(f"❌ JPG файлы не найдены в директории: {input_dir}")
        return
    
    print(f"\nПроект: {project_name}")
    print(f"📁 Найдено JPG файлов в исходной директории: {len(jpg_files)}")
    
    # Получаем список существующих видео-плейсхолдеров
    existing_videos = get_existing_video_placeholders(output_dir)
    
    if existing_videos:
        print(f"✓ Найдено существующих видео-плейсхолдеров: {len(existing_videos)}")
        print(f"  Примеры: {list(existing_videos)[:5]}{'...' if len(existing_videos) > 5 else ''}")
    else:
        print(f"✓ Существующих видео-плейсхолдеров не найдено")
    
    # Фильтруем список - оставляем только те, для которых нет видео
    files_to_process = []
    skipped_count = 0
    
    for image_path in jpg_files:
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if base_name in existing_videos:
            skipped_count += 1
        else:
            files_to_process.append(image_path)
    
    print(f"\n📊 Статистика:")
    print(f"  Всего JPG файлов: {len(jpg_files)}")
    print(f"  Уже обработано: {skipped_count}")
    print(f"  Нужно обработать: {len(files_to_process)}")
    
    if not files_to_process:
        print("\n✓ Все видео-плейсхолдеры уже созданы! Нечего делать.")
        return
    
    print(f"\nВходная директория: {input_dir}")
    print(f"Выходная директория: {output_dir}")
    print(f"Файл с царапинами: {scratches_path}")
    print(f"Альфа-маска: {alpha_mask_path}")
    print(f"Формат вывода: ProRes 4444 с альфа-каналом")
    
    successful_videos = 0
    failed_videos = 0
    
    for i, image_path in enumerate(files_to_process, 1):
        print(f"\n[{i}/{len(files_to_process)}] Обрабатываю: {os.path.basename(image_path)}")
        
        # Проверяем соотношение сторон
        if not check_image_aspect_ratio(image_path):
            print(f"  ⚠️  Пропускаю файл с неверным соотношением сторон")
            failed_videos += 1
            continue
        
        # Создаем имя выходного файла
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}.mov")
        
        # Создаем видео с наложением белых царапин и альфа-маски
        if create_video_placeholder(image_path, output_path, scratches_path, alpha_mask_path):
            successful_videos += 1
        else:
            failed_videos += 1
    
    print(f"\n=== РЕЗУЛЬТАТЫ ОБРАБОТКИ ===")
    print(f"✅ Успешно создано видео: {successful_videos}")
    print(f"❌ Ошибок: {failed_videos}")
    print(f"⏭️  Пропущено (уже существует): {skipped_count}")
    print(f"📊 Всего JPG файлов: {len(jpg_files)}")
    print(f"💾 Всего видео в директории: {len(existing_videos) + successful_videos}")
    
    if successful_videos > 0:
        print(f"\nГотовые видео сохранены в: {output_dir}")
        print(f"Формат: ProRes 4444 с альфа-каналом (царапины + альфа-маска)")

if __name__ == "__main__":
    main()
