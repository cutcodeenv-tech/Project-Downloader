#!/usr/bin/env python3
"""
Скрипт для упаковки JPG фотографий в MOV композиции с альфа каналом при помощи ffmpeg
"""

import os
import subprocess
import sys
from PIL import Image
import glob

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

def create_video_placeholder(image_path, output_path, scratches_path, blend_mode):
    """Создает MOV видео с наложением царапин из JPG изображения"""
    try:
        # Команда ffmpeg для создания видео с наложением царапин
        cmd = [
            'ffmpeg',
            '-y',  # Перезаписать выходной файл
            '-loop', '1',  # Зациклить изображение
            '-i', image_path,  # Входное изображение
            '-i', scratches_path,  # Файл с царапинами
            '-filter_complex', 
            f'[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[bg];'
            f'[1:v]format=rgba,colorchannelmixer=aa=0.5[scratches_50];'
            f'[bg][scratches_50]blend=all_mode={blend_mode}:all_opacity=1.0[final]',
            '-map', '[final]',
            '-c:v', 'libx264',  # Кодек H.264
            '-pix_fmt', 'yuv420p',  # Пиксельный формат
            '-r', '25',  # Частота кадров
            '-t', '10',  # Длительность 10 секунд
            output_path
        ]
        
        print(f"  🎬 Создаю видео: {os.path.basename(output_path)} (режим: {blend_mode})")
        
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
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        return
    
    # Пути к директориям и файлам
    input_dir = "/Users/theseus/Work/osnovateli_doc_bot/data/photo_16_9"
    output_dir = "/Users/theseus/Work/osnovateli_doc_bot/data/photo_placeholder"
    scratches_path = "/Users/theseus/Work/osnovateli_doc_bot/assets/scratches_add.mp4"
    
    # Проверяем существование входной директории
    if not os.path.exists(input_dir):
        print(f"❌ Входная директория не найдена: {input_dir}")
        return
    
    # Проверяем существование файла с царапинами
    if not os.path.exists(scratches_path):
        print(f"❌ Файл с царапинами не найден: {scratches_path}")
        return
    
    # Создаем выходную директорию
    os.makedirs(output_dir, exist_ok=True)
    
    # Ищем все JPG файлы в входной директории
    jpg_files = glob.glob(os.path.join(input_dir, "*.jpg"))
    jpg_files.extend(glob.glob(os.path.join(input_dir, "*.jpeg")))
    
    if not jpg_files:
        print(f"❌ JPG файлы не найдены в директории: {input_dir}")
        return
    
    print(f"\nНайдено {len(jpg_files)} JPG файлов")
    print(f"Входная директория: {input_dir}")
    print(f"Выходная директория: {output_dir}")
    print(f"Файл с царапинами: {scratches_path}")
    print(f"Режим наложения: screen")
    
    successful_videos = 0
    failed_videos = 0
    
    for i, image_path in enumerate(jpg_files, 1):
        print(f"\n[{i}/{len(jpg_files)}] Обрабатываю: {os.path.basename(image_path)}")
        
        # Проверяем соотношение сторон
        if not check_image_aspect_ratio(image_path):
            print(f"  ⚠️  Пропускаю файл с неверным соотношением сторон")
            failed_videos += 1
            continue
        
        # Создаем имя выходного файла
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}.mov")
        
        # Создаем видео с режимом screen (лучше для светлых элементов)
        if create_video_placeholder(image_path, output_path, scratches_path, 'screen'):
            successful_videos += 1
        else:
            failed_videos += 1
    
    print(f"\n=== РЕЗУЛЬТАТЫ ОБРАБОТКИ ===")
    print(f"Успешно создано видео: {successful_videos}")
    print(f"Ошибок: {failed_videos}")
    print(f"Всего обработано: {len(jpg_files)}")
    
    if successful_videos > 0:
        print(f"\nГотовые видео сохранены в: {output_dir}")
        print(f"Использован режим наложения: screen")

if __name__ == "__main__":
    main()
