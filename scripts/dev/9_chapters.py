#!/usr/bin/env python3
"""
Скрипт для создания видео с текстом из chapters.txt
"""

import os
import subprocess
import tempfile
import shutil
from PIL import Image, ImageDraw, ImageFont

def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

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

def ease_out_cubic(t):
    """
    Функция easing для плавного замедления анимации
    t: значение от 0 до 1 (прогресс анимации)
    Возвращает: скорректированное значение от 0 до 1
    Формула: 1 - (1 - t)^3
    """
    return 1 - (1 - t) ** 3

def read_text_from_file(file_path):
    """Читает текст из файла chapters.txt"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read().strip()
        if not text:
            print(f"❌ Файл {file_path} пуст")
            return None
        return text
    except FileNotFoundError:
        print(f"❌ Файл не найден: {file_path}")
        return None
    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
        return None

def create_text_frame(text, font_path, output_path, tracking_amount, width=1920, height=1080):
    """Создает кадр с текстом по центру с учетом tracking amount"""
    # Создаем изображение с прозрачным фоном
    image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Загружаем шрифт
    font_size = 100
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception as e:
        print(f"❌ Ошибка при загрузке шрифта: {e}")
        return False
    
    # Разбиваем текст на символы
    chars = list(text)
    if not chars:
        return False
    
    # Вычисляем ширину каждого символа и общую ширину без tracking
    char_widths = []
    total_width_no_tracking = 0
    
    for char in chars:
        bbox = draw.textbbox((0, 0), char, font=font)
        char_width = bbox[2] - bbox[0]
        char_widths.append(char_width)
        total_width_no_tracking += char_width
    
    # Вычисляем общую ширину с учетом tracking
    # Tracking добавляет расстояние между символами
    total_tracking = tracking_amount * (len(chars) - 1) if len(chars) > 1 else 0
    total_width = total_width_no_tracking + total_tracking
    
    # Вычисляем высоту текста (берем высоту первого символа)
    bbox = draw.textbbox((0, 0), chars[0], font=font)
    text_height = bbox[3] - bbox[1]
    
    # Начальная позиция для центрирования
    start_x = (width - total_width) // 2
    text_y = (height - text_height) // 2
    
    # Рисуем каждый символ отдельно с учетом tracking
    current_x = start_x
    text_color = (255, 255, 255, 255)
    
    for i, char in enumerate(chars):
        draw.text((current_x, text_y), char, fill=text_color, font=font)
        # Перемещаемся к следующему символу: ширина текущего + tracking
        current_x += char_widths[i] + tracking_amount
    
    # Сохраняем изображение
    image.save(output_path, 'PNG')
    return True

def create_video_from_frames(frames_dir, output_path, fps=25, duration=3, motion_blur=True, bg_video_path=None):
    """
    Создает видео из последовательности кадров с альфа-каналом
    motion_blur: если True, применяет motion blur для плавности движения
    bg_video_path: путь к фоновому видео (если None, используется прозрачный фон)
    """
    try:
        # FFmpeg ожидает последовательность файлов с нумерацией
        input_pattern = os.path.join(frames_dir, 'frame_%05d.png')
        
        if bg_video_path:
            # Композитинг с фоновым видео
            # Используем filter_complex для наложения текста поверх фона
            filter_complex_parts = []
            
            # Обрабатываем фоновое видео: обрезаем до нужной длительности
            # Если видео короче, оно будет зациклено через stream_loop
            filter_complex_parts.append(f'[0:v]trim=duration={duration},setpts=PTS-STARTPTS[bg]')
            
            # Обрабатываем текст: применяем motion blur если нужно
            text_filter = '[1:v]'
            if motion_blur:
                text_filter += 'tblend=all_mode=average:all_opacity=0.5,'
            text_filter += 'setpts=PTS-STARTPTS[text]'
            filter_complex_parts.append(text_filter)
            
            # Накладываем текст поверх фона
            filter_complex_parts.append('[bg][text]overlay=0:0[final]')
            
            filter_complex = ';'.join(filter_complex_parts)
            
            cmd = [
                'ffmpeg',
                '-y',
                '-stream_loop', '-1',  # Зацикливаем фоновое видео если оно короче
                '-i', bg_video_path,
                '-framerate', str(fps),
                '-i', input_pattern,
                '-filter_complex', filter_complex,
                '-map', '[final]',
                '-c:v', 'prores_ks',
                '-profile:v', '4444',
                '-pix_fmt', 'yuva444p10le',
                '-t', str(duration),
                output_path
            ]
        else:
            # Без фона - только текст с прозрачностью
            filter_parts = []
            
            if motion_blur:
                # Применяем motion blur через tblend (temporal blend)
                filter_parts.append('tblend=all_mode=average:all_opacity=0.5')
            
            cmd = [
                'ffmpeg',
                '-y',
                '-framerate', str(fps),
                '-i', input_pattern,
            ]
            
            # Добавляем фильтры если есть
            if filter_parts:
                cmd.extend(['-vf', ','.join(filter_parts)])
            
            # Добавляем параметры кодека
            cmd.extend([
                '-c:v', 'prores_ks',
                '-profile:v', '4444',
                '-pix_fmt', 'yuva444p10le',
                output_path
            ])
        
        print(f"  🎬 Создаю видео: {os.path.basename(output_path)}")
        if motion_blur:
            print(f"  📸 Motion blur включен")
        if bg_video_path:
            print(f"  🎥 Фоновое видео: {os.path.basename(bg_video_path)}")
        
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
    print("=== СКРИПТ СОЗДАНИЯ ВИДЕО С ТЕКСТОМ ===")
    
    # Получаем название проекта
    project_name = get_project_name()
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        return
    
    # Пути к файлам
    base_path = "/Users/theseus/Projects/osnovateli_doc_framework/data"
    chapters_file = os.path.join(base_path, project_name, "database", "chapters.txt")
    output_dir = os.path.join(base_path, project_name, "chapters")
    font_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/font/theater.bold-condensed.ttf"
    bg_video_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/chapters_bg.mp4"
    
    # Проверяем существование файла с текстом
    if not os.path.exists(chapters_file):
        print(f"❌ Файл не найден: {chapters_file}")
        return
    
    # Проверяем существование шрифта
    if not os.path.exists(font_path):
        print(f"❌ Шрифт не найден: {font_path}")
        return
    
    # Проверяем существование фонового видео
    if not os.path.exists(bg_video_path):
        print(f"❌ Фоновое видео не найдено: {bg_video_path}")
        return
    
    # Создаем выходную директорию
    os.makedirs(output_dir, exist_ok=True)
    
    # Читаем текст из файла
    text = read_text_from_file(chapters_file)
    if not text:
        return
    
    print(f"\n✓ Текст прочитан: {text[:50]}{'...' if len(text) > 50 else ''}")
    
    # Создаем временную директорию для кадров
    frames_dir = tempfile.mkdtemp()
    
    try:
        # Параметры анимации
        duration = 3  # секунды
        fps = 25
        total_frames = duration * fps
        tracking_start = 0
        tracking_end = 20
        
        print(f"\n📝 Создаю {total_frames} кадров анимации...")
        
        # Генерируем кадры
        for frame_num in range(total_frames):
            # Вычисляем прогресс от 0 до 1
            progress = frame_num / (total_frames - 1) if total_frames > 1 else 0
            # Применяем функцию easing для плавного замедления
            eased_progress = ease_out_cubic(progress)
            # Вычисляем tracking amount с учетом easing
            tracking_amount = tracking_start + (tracking_end - tracking_start) * eased_progress
            
            # Создаем путь к файлу кадра
            frame_path = os.path.join(frames_dir, f"frame_{frame_num + 1:05d}.png")
            
            # Создаем кадр
            if not create_text_frame(text, font_path, frame_path, tracking_amount):
                print(f"❌ Ошибка при создании кадра {frame_num + 1}")
                return
            
            if (frame_num + 1) % 25 == 0:
                print(f"  Обработано кадров: {frame_num + 1}/{total_frames}")
        
        print(f"  ✓ Все кадры созданы")
        
        # Создаем видео из кадров с фоновым видео
        output_path = os.path.join(output_dir, "chapter.mov")
        if create_video_from_frames(frames_dir, output_path, fps, duration, motion_blur=True, bg_video_path=bg_video_path):
            print(f"\n✓ Видео сохранено: {output_path}")
        else:
            print(f"\n❌ Не удалось создать видео")
    
    finally:
        # Удаляем временную директорию с кадрами
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir)

if __name__ == "__main__":
    main()

