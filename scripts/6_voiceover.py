import os
import re
import sys
import subprocess
import yaml
from datetime import datetime

# Проверка и автоматическая установка необходимых зависимостей
def check_and_install_dependencies():
    """Проверяет наличие зависимостей и устанавливает их при необходимости"""
    
    # Проверка whisper
    try:
        subprocess.run(['whisper', '--help'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("⚠️  Whisper не найден")
        print("📦 Для установки whisper выполните:")
        print("   pip install openai-whisper")
        print("\n❌ Установите whisper и запустите скрипт снова")
        sys.exit(1)
    
    # Проверка PyYAML
    try:
        import yaml
    except ImportError:
        print("📦 Библиотека PyYAML не найдена")
        print("🔄 Автоматическая установка PyYAML...")
        
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'PyYAML'])
            print("✓ Библиотека PyYAML успешно установлена!")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Ошибка установки: {e}")
            print("\n💡 Попробуйте установить вручную:")
            print("   pip3 install PyYAML")
            sys.exit(1)

# Проверяем зависимости при запуске
check_and_install_dependencies()

def check_existing_files(project_dir):
    """Проверяет наличие уже созданных файлов для корректной работы при повторном запуске"""
    database_dir = os.path.join(project_dir, 'database')
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    
    # Проверяем существующие файлы
    existing_files = []
    
    # Проверяем txt файл с расшифровкой
    txt_file = os.path.join(database_dir, 'transcription.txt')
    if os.path.exists(txt_file):
        existing_files.append(f"📄 Расшифровка: {txt_file}")
    
    # Проверяем YAML файл
    yaml_file = os.path.join(data_dir, 'transcription_timeline.yaml')
    if os.path.exists(yaml_file):
        existing_files.append(f"📄 YAML таймлайн: {yaml_file}")
    
    if existing_files:
        print("⚠️  Найдены существующие файлы:")
        for file in existing_files:
            print(f"   {file}")
        
        choice = input("\nПерезаписать существующие файлы? (y/n): ").strip().lower()
        if choice != 'y':
            print("❌ Операция отменена")
            return False
    
    return True

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

def find_audio_file(voiceover_dir, project_name):
    """
    Находит аудиофайл в директории voiceover
    Приоритет: {project_name}_voiceover.wav, затем любой аудиофайл
    """
    if not os.path.exists(voiceover_dir):
        print(f"❌ Директория voiceover не найдена: {voiceover_dir}")
        return None
    
    # Ищем файл с ожидаемым названием
    expected_filename = f"{project_name}_voiceover.wav"
    expected_path = os.path.join(voiceover_dir, expected_filename)
    
    if os.path.exists(expected_path):
        print(f"✓ Найден аудиофайл: {expected_filename}")
        return expected_path
    
    # Ищем любой аудиофайл
    audio_extensions = ['.wav', '.mp3', '.m4a', '.aiff', '.flac']
    audio_files = []
    
    for file in os.listdir(voiceover_dir):
        if any(file.lower().endswith(ext) for ext in audio_extensions):
            if os.path.isfile(os.path.join(voiceover_dir, file)):
                audio_files.append(file)
    
    if not audio_files:
        print(f"❌ В директории voiceover не найдено аудиофайлов")
        return None
        
    if len(audio_files) > 1:
        print(f"⚠️  Найдено {len(audio_files)} аудиофайлов:")
        for i, f in enumerate(audio_files, 1):
            print(f"  {i}. {f}")
        print(f"⚠️  Использую первый файл: {audio_files[0]}")
    
    audio_path = os.path.join(voiceover_dir, audio_files[0])
    print(f"✓ Найден аудиофайл: {audio_files[0]}")
    return audio_path

def transcribe_audio(audio_path, project_name):
    """
    Транскрибирует аудиофайл с помощью Whisper
    Использует модель medium для лучшего качества русского языка
    """
    print(f"\n=== ТРАНСКРИПЦИЯ АУДИО ===")
    print(f"Файл: {os.path.basename(audio_path)}")
    print("🤖 Запускаю Whisper с моделью medium...")
    
    try:
        # Команда для Whisper с моделью medium и русским языком
        cmd = [
            'whisper', 
            audio_path,
            '--model', 'medium',
            '--language', 'ru',
            '--output_format', 'json',
            '--word_timestamps', 'True'
        ]
        
        print("⏳ Обработка может занять несколько минут...")
        print("📊 Прогресс транскрипции:")
        
        import time
        start_time = time.time()
        
        # Получаем размер исходного файла для примерной оценки времени
        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            print(f"   📁 Размер файла: {file_size_mb:.1f} MB")
            estimated_time = file_size_mb * 2  # примерно 2 секунды на MB для модели medium
            print(f"   ⏱️  Примерное время: {estimated_time:.0f} секунд")
        except:
            pass
        
        # Запускаем процесс с выводом в реальном времени
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Читаем вывод построчно и показываем прогресс
        last_update = time.time()
        has_output = False
        
        while True:
            # Проверяем stdout
            stdout_line = process.stdout.readline()
            if stdout_line:
                has_output = True
                line = stdout_line.strip()
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Показываем все сообщения от Whisper
                if line:
                    print(f"   [{elapsed:.0f}с] {line}")
                    last_update = current_time
            
            # Проверяем stderr
            stderr_line = process.stderr.readline()
            if stderr_line:
                has_output = True
                line = stderr_line.strip()
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Показываем все сообщения от Whisper
                if line:
                    print(f"   [{elapsed:.0f}с] {line}")
                    last_update = current_time
            
            # Проверяем завершение процесса
            if process.poll() is not None:
                break
            
            # Если нет вывода более 5 секунд, показываем статус
            current_time = time.time()
            if current_time - last_update > 5:
                elapsed = current_time - start_time
                print(f"   [{elapsed:.0f}с] Обработка продолжается...")
                last_update = current_time
                
                # Проверяем создание промежуточных файлов
                base_name = os.path.splitext(audio_path)[0]
                temp_files = [f"{base_name}.txt", f"{base_name}.srt", f"{base_name}.vtt"]
                for temp_file in temp_files:
                    if os.path.exists(temp_file):
                        print(f"   [{elapsed:.0f}с] ✓ Создан промежуточный файл: {os.path.basename(temp_file)}")
                        break
        
        # Ждем завершения процесса
        return_code = process.poll()
        total_time = time.time() - start_time
        
        if not has_output:
            print(f"   [{total_time:.0f}с] Whisper работает без вывода (это нормально)")
        
        if return_code != 0:
            print(f"❌ Whisper завершился с ошибкой (код: {return_code})")
            # Показываем последние сообщения об ошибке
            stdout, stderr = process.communicate()
            if stderr:
                print(f"Ошибка: {stderr}")
            return None
        
        # Whisper создает файлы с тем же именем, но с расширениями
        base_name = os.path.splitext(audio_path)[0]
        json_file = f"{base_name}.json"
        
        if os.path.exists(json_file):
            print(f"✓ Транскрипция завершена за {total_time:.1f} секунд: {json_file}")
            return json_file
        else:
            print("❌ JSON файл не найден")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка транскрипции: {e}")
        print(f"Вывод: {e.stderr}")
        return None
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return None

def save_transcription_txt(json_file, database_dir):
    """
    Сохраняет расшифровку в txt файл в директории database
    """
    print(f"\n=== СОХРАНЕНИЕ РАСШИФРОВКИ ===")
    
    try:
        import json
        
        # Читаем JSON файл
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Извлекаем текст
        text = data.get('text', '').strip()
        
        if not text:
            print("❌ Текст не найден в JSON файле")
            return None
        
        # Создаем database директорию если её нет
        os.makedirs(database_dir, exist_ok=True)
        
        # Сохраняем в txt файл
        txt_path = os.path.join(database_dir, 'transcription.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"✓ Расшифровка сохранена: {txt_path}")
        print(f"✓ Длина текста: {len(text)} символов")
        
        return txt_path
        
    except Exception as e:
        print(f"❌ Ошибка сохранения расшифровки: {e}")
        return None

def create_yaml_timeline(json_file, data_dir):
    """
    Создает YAML разметку с таймкодами и сохраняет в директории data
    """
    print(f"\n=== СОЗДАНИЕ YAML ТАЙМЛАЙНА ===")
    
    try:
        import json
        
        # Читаем JSON файл
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Извлекаем сегменты с таймкодами
        segments = data.get('segments', [])
        
        if not segments:
            print("❌ Сегменты не найдены в JSON файле")
            return None
        
        # Создаем YAML структуру
        timeline_data = {
            'project': {
                'name': 'voiceover_transcription',
                'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_segments': len(segments)
            },
            'segments': []
        }
        
        for i, segment in enumerate(segments, 1):
            segment_data = {
                'id': i,
                'start_time': segment.get('start', 0),
                'end_time': segment.get('end', 0),
                'duration': segment.get('end', 0) - segment.get('start', 0),
                'text': segment.get('text', '').strip(),
                'confidence': segment.get('avg_logprob', 0)
            }
            timeline_data['segments'].append(segment_data)
        
        # Сохраняем YAML файл
        yaml_path = os.path.join(data_dir, 'transcription_timeline.yaml')
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(timeline_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        print(f"✓ YAML таймлайн создан: {yaml_path}")
        print(f"✓ Сегментов: {len(segments)}")
        
        return yaml_path
        
    except Exception as e:
        print(f"❌ Ошибка создания YAML: {e}")
        return None

def main():
    print("=" * 60)
    print("СКРИПТ ТРАНСКРИПЦИИ VOICEOVER С ПОМОЩЬЮ WHISPER")
    print("=" * 60)
    
    # Получаем название проекта
    project_name = get_project_name()
    
    # Определяем пути
    data_dir = '/Users/theseus/Projects/osnovateli_doc_framework/data'
    project_dir = os.path.join(data_dir, project_name)
    
    # Проверяем существование проекта
    if not os.path.exists(project_dir):
        print(f"\n❌ Проект не найден: {project_dir}")
        print("💡 Сначала создайте структуру проекта с помощью скрипта 0_structure.py")
        return
    
    print(f"\n✓ Проект найден: {project_name}")
    
    # Проверяем существующие файлы
    if not check_existing_files(project_dir):
        return
    
    # Определяем директории
    voiceover_dir = os.path.join(project_dir, 'voiceover')
    database_dir = os.path.join(project_dir, 'database')
    
    # Шаг 1: Находим аудиофайл
    print(f"\n{'='*60}")
    print("ШАГ 1: ПОИСК АУДИОФАЙЛА")
    print(f"{'='*60}")
    audio_path = find_audio_file(voiceover_dir, project_name)
    
    if not audio_path:
        print("\n❌ Аудиофайл не найден!")
        print(f"💡 Поместите аудиофайл в директорию: {voiceover_dir}")
        return
    
    # Шаг 2: Транскрибируем аудио
    print(f"\n{'='*60}")
    print("ШАГ 2: ТРАНСКРИПЦИЯ АУДИО")
    print(f"{'='*60}")
    json_file = transcribe_audio(audio_path, project_name)
    
    if not json_file:
        print("\n❌ Транскрипция не удалась")
        return
    
    # Шаг 3: Сохраняем расшифровку в txt
    print(f"\n{'='*60}")
    print("ШАГ 3: СОХРАНЕНИЕ РАСШИФРОВКИ")
    print(f"{'='*60}")
    txt_path = save_transcription_txt(json_file, database_dir)
    
    if not txt_path:
        print("\n❌ Не удалось сохранить расшифровку")
        return
    
    # Шаг 4: Создаем YAML таймлайн
    print(f"\n{'='*60}")
    print("ШАГ 4: СОЗДАНИЕ YAML ТАЙМЛАЙНА")
    print(f"{'='*60}")
    yaml_path = create_yaml_timeline(json_file, data_dir)
    
    if not yaml_path:
        print("\n❌ Не удалось создать YAML таймлайн")
        return
    
    # Итоговая информация
    print(f"\n{'='*60}")
    print("✅ ГОТОВО!")
    print(f"{'='*60}")
    print(f"📄 Расшифровка: {txt_path}")
    print(f"📄 YAML таймлайн: {yaml_path}")
    print(f"📄 JSON файл: {json_file}")
    print(f"\n💡 Все файлы успешно созданы!")

if __name__ == "__main__":
    main()
