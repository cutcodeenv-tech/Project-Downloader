import os
import sys
import subprocess
from pathlib import Path
from path_utils import get_data_dir

def check_and_install_dependencies():
    """Проверяет и устанавливает необходимые зависимости"""
    print("=== ПРОВЕРКА ЗАВИСИМОСТЕЙ ===")

    python_version = sys.version_info
    print(f"ℹ️  Python {python_version.major}.{python_version.minor} обнаружен")

    # Обязательные зависимости
    required_packages = {
        'cv2': 'opencv-contrib-python',
        'numpy': 'numpy'
    }

    missing_packages = []

    print()
    for package_name, pip_name in required_packages.items():
        try:
            __import__(package_name)
            print(f"✓ {package_name} уже установлен")
        except ImportError:
            missing_packages.append((package_name, pip_name))
            print(f"❌ {package_name} не найден")

    if missing_packages:
        print(f"\nУстанавливаю недостающие пакеты...")
        for package_name, pip_name in missing_packages:
            try:
                print(f"Устанавливаю {pip_name}...")
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', pip_name, '--user'])
                print(f"✓ {pip_name} успешно установлен")
            except subprocess.CalledProcessError as e:
                print(f"❌ Ошибка при установке {pip_name}: {e}")
                return False

    # Проверяем MediaPipe (опционально для Python 3.10+)
    print(f"\n--- Расширенная детекция лиц ---")
    try:
        import mediapipe
        print(f"✓ MediaPipe установлен - будет использоваться улучшенная детекция")
    except ImportError:
        if python_version.major == 3 and python_version.minor < 10:
            print(f"⚠️  MediaPipe требует Python 3.10+, у вас Python {python_version.major}.{python_version.minor}")
            print(f"   Будет использоваться Haar Cascades (анфас + профили)")
            print(f"   Для лучшей точности обновите Python: brew install python@3.11")
        else:
            print(f"⚠️  MediaPipe не установлен")
            print(f"   Установите для улучшенной детекции: pip install mediapipe --user")
            print(f"   Будет использоваться Haar Cascades")

    print("\n✓ Все обязательные зависимости готовы\n")
    return True

def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def is_image_file(filename):
    """Проверяет, является ли файл изображением"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
    return Path(filename).suffix.lower() in image_extensions

def get_existing_cropped_images(output_dir):
    """
    Получает список существующих обработанных изображений в выходной директории
    Возвращает set с именами файлов без расширения (например, {'B3_1', 'B4_1', ...})
    """
    existing = set()

    if not os.path.exists(output_dir):
        return existing

    # Ищем все файлы .jpg в директории
    for filename in os.listdir(output_dir):
        if filename.endswith('.jpg') and os.path.isfile(os.path.join(output_dir, filename)):
            # Извлекаем имя без расширения (например, "B3_1.jpg" -> "B3_1")
            name_without_ext = Path(filename).stem
            existing.add(name_without_ext)

    return existing

def detect_faces_mediapipe(image):
    """
    Детектирует лица на изображении с помощью MediaPipe (приоритетный метод)

    Args:
        image: входное изображение (BGR)

    Returns:
        list: список обнаруженных лиц [(x, y, w, h), ...] или пустой список
    """
    try:
        import mediapipe as mp

        mp_face_detection = mp.solutions.face_detection

        # Конвертируем BGR в RGB для MediaPipe
        image_rgb = image[:, :, ::-1].copy()
        height, width = image.shape[:2]

        faces = []

        # Используем контекстный менеджер для Face Detection
        with mp_face_detection.FaceDetection(
            model_selection=1,  # 1 = полный диапазон (0 = близкие лица)
            min_detection_confidence=0.5
        ) as face_detection:

            results = face_detection.process(image_rgb)

            if results.detections:
                for detection in results.detections:
                    # Получаем относительные координаты bounding box
                    bbox = detection.location_data.relative_bounding_box

                    # Конвертируем в абсолютные координаты
                    x = int(bbox.xmin * width)
                    y = int(bbox.ymin * height)
                    w = int(bbox.width * width)
                    h = int(bbox.height * height)

                    # Проверяем валидность координат
                    if x >= 0 and y >= 0 and w > 0 and h > 0:
                        faces.append((x, y, w, h))

        return faces

    except Exception as e:
        print(f"  ⚠️  Ошибка при детекции лиц (MediaPipe): {e}")
        print(f"     Переключаюсь на Haar Cascades...")
        return []

def detect_faces_haar(image):
    """
    Детектирует лица на изображении с помощью улучшенного Haar Cascades

    Использует множественные классификаторы и проходы:
    - Фронтальные лица (анфас)
    - Профили (левый и правый)
    - Альтернативный детектор для сложных случаев

    Args:
        image: входное изображение (BGR)

    Returns:
        list: список обнаруженных лиц [(x, y, w, h), ...]
    """
    import cv2

    try:
        # Преобразуем в grayscale для лучшей детекции
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        min_face_size = min(width, height) // 20  # минимум 5% от меньшей стороны

        all_faces = []

        # 1. Детекция фронтальных лиц (строгий режим)
        face_cascade_default = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        faces = face_cascade_default.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(min_face_size, min_face_size)
        )
        all_faces.extend(faces)

        # 2. Если ничего не нашли - пробуем альтернативный детектор (более чувствительный)
        if len(all_faces) == 0:
            face_cascade_alt = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
            )
            faces = face_cascade_alt.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(min_face_size, min_face_size)
            )
            all_faces.extend(faces)

        # 3. Детекция профилей (если всё ещё ничего не нашли)
        if len(all_faces) == 0:
            profile_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_profileface.xml'
            )
            # Проверяем оригинальное изображение
            faces = profile_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=(min_face_size, min_face_size)
            )
            all_faces.extend(faces)

            # Проверяем отражённое изображение (для профилей в другую сторону)
            if len(faces) == 0:
                gray_flipped = cv2.flip(gray, 1)
                faces_flipped = profile_cascade.detectMultiScale(
                    gray_flipped,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(min_face_size, min_face_size)
                )
                # Корректируем координаты для отражённых лиц
                for (x, y, w, h) in faces_flipped:
                    all_faces.append((width - x - w, y, w, h))

        # Удаляем дубликаты (перекрывающиеся детекции)
        if len(all_faces) > 1:
            all_faces = remove_overlapping_faces(all_faces)

        return all_faces

    except Exception as e:
        print(f"  ⚠️  Ошибка при детекции лиц (Haar): {e}")
        return []

def remove_overlapping_faces(faces, overlap_threshold=0.3):
    """
    Удаляет перекрывающиеся детекции лиц

    Args:
        faces: список лиц [(x, y, w, h), ...]
        overlap_threshold: порог перекрытия (0.3 = 30%)

    Returns:
        list: отфильтрованный список лиц
    """
    if len(faces) == 0:
        return []

    # Сортируем по площади (большие лица приоритетнее)
    faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)

    filtered_faces = []

    for face in faces_sorted:
        x1, y1, w1, h1 = face
        is_duplicate = False

        for existing_face in filtered_faces:
            x2, y2, w2, h2 = existing_face

            # Вычисляем пересечение
            x_overlap = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
            y_overlap = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            overlap_area = x_overlap * y_overlap

            # Площадь меньшего прямоугольника
            area1 = w1 * h1
            area2 = w2 * h2
            min_area = min(area1, area2)

            # Если перекрытие больше порога - это дубликат
            if overlap_area > overlap_threshold * min_area:
                is_duplicate = True
                break

        if not is_duplicate:
            filtered_faces.append(face)

    return filtered_faces

def detect_faces(image):
    """
    Детектирует лица на изображении, используя каскадный подход

    Приоритеты:
    1. MediaPipe Face Detection (высокая точность)
    2. Haar Cascades (fallback)

    Args:
        image: входное изображение (BGR)

    Returns:
        tuple: (faces, method) где faces = [(x, y, w, h), ...], method = название метода
    """
    # Приоритет 1: MediaPipe
    faces = detect_faces_mediapipe(image)
    if len(faces) > 0:
        return faces, "MediaPipe"

    # Приоритет 2: Haar Cascades
    faces = detect_faces_haar(image)
    if len(faces) > 0:
        return faces, "Haar Cascades"

    return [], "Не обнаружено"

def calculate_faces_center(faces, image_width, image_height):
    """
    Вычисляет центр внимания на основе найденных лиц

    Args:
        faces: список лиц [(x, y, w, h), ...]
        image_width: ширина изображения
        image_height: высота изображения

    Returns:
        tuple: (center_x, center_y) координаты центра всех лиц
    """
    if len(faces) == 0:
        return None

    # Вычисляем центр каждого лица и среднюю точку
    total_x = 0
    total_y = 0

    for (x, y, w, h) in faces:
        face_center_x = x + w // 2
        face_center_y = y + h // 2
        total_x += face_center_x
        total_y += face_center_y

    # Среднее арифметическое центров всех лиц
    center_x = total_x // len(faces)
    center_y = total_y // len(faces)

    return center_x, center_y

def calculate_saliency_center(image):
    """
    Вычисляет центр значимой области изображения с помощью Saliency Detection

    Args:
        image: входное изображение (BGR)

    Returns:
        tuple: (center_x, center_y) координаты центра значимой области
    """
    import cv2
    import numpy as np

    try:
        # Создаём детектор saliency
        saliency = cv2.saliency.StaticSaliencyFineGrained_create()

        # Вычисляем saliency map
        success, saliency_map = saliency.computeSaliency(image)

        if not success:
            print("  ⚠️  Не удалось вычислить saliency map, используется центр изображения")
            return image.shape[1] // 2, image.shape[0] // 2

        # Нормализуем и преобразуем в бинарную карту
        saliency_map = (saliency_map * 255).astype("uint8")
        threshold_value = np.mean(saliency_map)
        _, binary_map = cv2.threshold(saliency_map, threshold_value, 255, cv2.THRESH_BINARY)

        # Вычисляем центр масс
        moments = cv2.moments(binary_map)

        if moments["m00"] != 0:
            center_x = int(moments["m10"] / moments["m00"])
            center_y = int(moments["m01"] / moments["m00"])
        else:
            # Если не удалось вычислить моменты, используем центр изображения
            center_x = image.shape[1] // 2
            center_y = image.shape[0] // 2

        return center_x, center_y

    except Exception as e:
        print(f"  ⚠️  Ошибка при вычислении saliency: {e}")
        # В случае ошибки возвращаем центр изображения
        return image.shape[1] // 2, image.shape[0] // 2

def calculate_crop_box(image, center_x, center_y, target_ratio=16/9, use_rule_of_thirds=False):
    """
    Вычисляет координаты рамки для кадрирования в нужном соотношении сторон

    Args:
        image: входное изображение
        center_x: x-координата центра значимой области
        center_y: y-координата центра значимой области
        target_ratio: целевое соотношение сторон (по умолчанию 16:9)
        use_rule_of_thirds: если True, применяет правило третей (объект на верхней линии 1/3)

    Returns:
        tuple: (x1, y1, x2, y2) координаты рамки кадрирования
    """
    height, width = image.shape[:2]
    current_ratio = width / height

    # Определяем размеры рамки
    if current_ratio > target_ratio:
        # Изображение шире целевого соотношения - ограничиваем по высоте
        crop_height = height
        crop_width = int(crop_height * target_ratio)
    else:
        # Изображение уже целевого соотношения - ограничиваем по ширине
        crop_width = width
        crop_height = int(crop_width / target_ratio)

    # Вычисляем координаты рамки
    # По горизонтали всегда центрируем
    x1 = center_x - crop_width // 2
    x2 = x1 + crop_width

    # По вертикали применяем правило третей если указано
    if use_rule_of_thirds:
        # Правило третей: объект на верхней линии (1/3 от высоты кадра)
        # Это значит, что объект должен быть на 33.3% от верха итогового кадра
        y1 = center_y - crop_height // 3
        y2 = y1 + crop_height
    else:
        # Стандартное центрирование
        y1 = center_y - crop_height // 2
        y2 = y1 + crop_height

    # Корректируем координаты, если рамка выходит за пределы изображения
    if x1 < 0:
        x2 = min(x2 - x1, width)
        x1 = 0
    elif x2 > width:
        x1 = max(0, x1 - (x2 - width))
        x2 = width

    if y1 < 0:
        y2 = min(y2 - y1, height)
        y1 = 0
    elif y2 > height:
        y1 = max(0, y1 - (y2 - height))
        y2 = height

    return int(x1), int(y1), int(x2), int(y2)

def smart_crop_image(input_path, output_path, target_width=1920, target_height=1080):
    """
    Выполняет интеллектуальное кадрирование изображения

    Приоритеты детекции:
    1. Люди/лица (Haar Cascades)
    2. Значимые области (Saliency Detection)
    3. Геометрический центр (fallback)

    Args:
        input_path: путь к входному изображению
        output_path: путь для сохранения результата
        target_width: целевая ширина (по умолчанию 1920)
        target_height: целевая высота (по умолчанию 1080)

    Returns:
        bool: True если обработка успешна, False в противном случае
    """
    import cv2

    try:
        # Загружаем изображение
        image = cv2.imread(input_path)

        if image is None:
            print(f"  ❌ Не удалось загрузить изображение: {input_path}")
            return False

        height, width = image.shape[:2]
        print(f"  📏 Исходный размер: {width}x{height}")

        # Приоритет 1: Пытаемся найти лица (MediaPipe → Haar)
        faces, detection_method = detect_faces(image)
        use_rule_of_thirds = False  # Флаг для применения правила третей

        if len(faces) > 0:
            print(f"  👤 Обнаружено лиц: {len(faces)} (метод: {detection_method})")
            center_result = calculate_faces_center(faces, width, height)
            if center_result:
                center_x, center_y = center_result
                use_rule_of_thirds = True  # Применяем правило третей для лиц
                print(f"  🎯 Центр внимания (лица): ({center_x}, {center_y})")
                print(f"  📐 Применяется правило третей (верхняя линия)")
            else:
                # Fallback на saliency
                center_x, center_y = calculate_saliency_center(image)
                print(f"  🎯 Центр значимой области (saliency): ({center_x}, {center_y})")
        else:
            # Приоритет 2: Используем Saliency Detection
            print(f"  👤 Лица не обнаружены, используется saliency detection")
            center_x, center_y = calculate_saliency_center(image)
            print(f"  🎯 Центр значимой области: ({center_x}, {center_y})")

        # Вычисляем рамку кадрирования (с правилом третей для лиц)
        x1, y1, x2, y2 = calculate_crop_box(image, center_x, center_y, use_rule_of_thirds=use_rule_of_thirds)
        print(f"  ✂️  Рамка кадрирования: ({x1}, {y1}) - ({x2}, {y2})")

        # Обрезаем изображение
        cropped_image = image[y1:y2, x1:x2]

        # Изменяем размер до целевого разрешения
        resized_image = cv2.resize(cropped_image, (target_width, target_height),
                                   interpolation=cv2.INTER_LANCZOS4)

        # Сохраняем результат
        cv2.imwrite(output_path, resized_image)
        print(f"  ✅ Сохранено: {target_width}x{target_height}")

        return True

    except Exception as e:
        print(f"  ❌ Ошибка при обработке изображения: {e}")
        return False

def process_images(pictures_dir, output_dir):
    """
    Обрабатывает все изображения в указанной директории
    При повторном запуске обрабатывает только новые изображения

    Args:
        pictures_dir: директория с исходными изображениями
        output_dir: директория для сохранения результатов

    Returns:
        tuple: (успешно обработано, пропущено, ошибок)
    """
    # Создаём выходную директорию, если её нет
    os.makedirs(output_dir, exist_ok=True)

    # Получаем список файлов
    files = [f for f in os.listdir(pictures_dir) if os.path.isfile(os.path.join(pictures_dir, f))]
    image_files = [f for f in files if is_image_file(f)]

    if not image_files:
        print("❌ В директории не найдено изображений!")
        return 0, 0, 0

    print(f"\n📁 Найдено изображений в исходной директории: {len(image_files)}")

    # Получаем список существующих обработанных изображений
    existing_cropped = get_existing_cropped_images(output_dir)

    if existing_cropped:
        print(f"✓ Найдено существующих обработанных изображений: {len(existing_cropped)}")
        print(f"  Примеры: {list(existing_cropped)[:5]}{'...' if len(existing_cropped) > 5 else ''}")
    else:
        print(f"✓ Существующих обработанных изображений не найдено")

    # Фильтруем список - оставляем только те, для которых нет обработанной версии
    images_to_process = []
    skipped_count = 0

    for filename in image_files:
        name_without_ext = Path(filename).stem
        if name_without_ext in existing_cropped:
            skipped_count += 1
        else:
            images_to_process.append(filename)

    print(f"\n📊 Статистика:")
    print(f"  Всего изображений: {len(image_files)}")
    print(f"  Уже обработано: {skipped_count}")
    print(f"  Нужно обработать: {len(images_to_process)}")

    if not images_to_process:
        print("\n✓ Все изображения уже обработаны! Нечего делать.")
        return 0, skipped_count, 0

    print(f"\n📤 Выходная директория: {output_dir}")
    print(f"🎬 Целевой формат: 16:9 (1920x1080)\n")

    successful = 0
    errors = 0

    for i, filename in enumerate(images_to_process, 1):
        print(f"\n[{i}/{len(images_to_process)}] Обрабатываю: {filename}")

        input_path = os.path.join(pictures_dir, filename)
        # Сохраняем с тем же именем, но меняем расширение на .jpg
        output_filename = Path(filename).stem + '.jpg'
        output_path = os.path.join(output_dir, output_filename)

        if smart_crop_image(input_path, output_path):
            successful += 1
        else:
            errors += 1

    return successful, skipped_count, errors

def main():
    """Основная функция скрипта"""
    print("=" * 70)
    print("=== ИНТЕЛЛЕКТУАЛЬНОЕ КАДРИРОВАНИЕ ИЗОБРАЖЕНИЙ (16:9) ===")
    print("===   С ПРИОРИТЕТОМ НА ЛЮДЕЙ (УЛУЧШЕННАЯ ДЕТЕКЦИЯ)   ===")
    print("=" * 70)
    print()

    import argparse
    parser = argparse.ArgumentParser(add_help=True, description="Интеллектуальное кадрирование 16:9")
    parser.add_argument("--input", dest="input_dir", default=None,
                        help="Папка с исходными изображениями (вместо структуры проекта)")
    parser.add_argument("--output", dest="output_dir", default=None,
                        help="Папка для результата (по умолчанию <input>/../images_cropped)")
    args, _ = parser.parse_known_args()

    # Проверяем и устанавливаем зависимости
    if not check_and_install_dependencies():
        print("❌ Не удалось установить необходимые зависимости!")
        return

    # Режим внешней папки: пути заданы явно, структура проекта не нужна.
    if args.input_dir:
        pictures_dir = Path(args.input_dir).expanduser()
        output_dir = (
            Path(args.output_dir).expanduser()
            if args.output_dir
            else pictures_dir.parent / "images_cropped"
        )
        print(f"\n📂 Внешняя папка")
        print(f"📥 Исходная директория: {pictures_dir}")
    else:
        # Запрашиваем название проекта
        project_name = os.getenv("PROJECT_NAME", "").strip() or get_project_name()

        # Определяем пути
        projects_root = get_data_dir(__file__)
        upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
        base_images = projects_root / project_name / 'images'
        base_cropped = projects_root / project_name / 'images_cropped'
        pictures_dir = base_images / upd_subdir if upd_subdir else base_images
        output_dir = base_cropped / upd_subdir if upd_subdir else base_cropped

        print(f"\n📂 Проект: {project_name}")
        if upd_subdir:
            print(f"🌊 Волна правок: {upd_subdir}")
        print(f"📥 Исходная директория: {pictures_dir}")

    # Проверяем существование директории с изображениями
    if not pictures_dir.exists():
        print(f"\n❌ Директория не найдена: {pictures_dir}")
        print("Убедитесь, что путь правильный и в папке есть изображения.")
        return

    # Обрабатываем изображения
    successful, skipped, errors = process_images(str(pictures_dir), str(output_dir))

    # Выводим статистику
    print("\n" + "=" * 70)
    print("=== РЕЗУЛЬТАТЫ ОБРАБОТКИ ===")
    print("=" * 70)
    print(f"✅ Успешно обработано: {successful}")
    print(f"⏭️  Пропущено (уже существует): {skipped}")
    print(f"❌ Ошибок: {errors}")
    print(f"📊 Всего файлов: {successful + skipped + errors}")
    print(f"\n💾 Результаты сохранены в: {output_dir}")
    print("=" * 70)

if __name__ == "__main__":
    main()
