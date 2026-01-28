#!/usr/bin/env python3
"""
Скрипт для создания скриншотов веб-страниц из other_links.csv
Использует Playwright для надежного скачивания даже сложных сайтов
"""
import os
import csv
import sys
import time
import random
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright не установлен!")
    print("Установите его командами:")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)


def get_project_name():
    """Запрашивает название проекта у пользователя"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')


def get_project_database_dir(project_name: str) -> Path:
    """Возвращает путь к директории database для указанного проекта"""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "database"


def get_project_screenshots_dir(project_name: str) -> Path:
    """Возвращает путь к директории screenshots для указанного проекта"""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "screenshots"


def get_other_links_csv_path(project_name: str) -> Path:
    """Возвращает путь к CSV файлу с other ссылками"""
    return get_project_database_dir(project_name) / f"osnovateli_doc_{project_name}_other_links.csv"


def read_links_from_csv(file_path: Path) -> List[Tuple[str, str]]:
    """Читает ссылки из CSV файла.
    
    Возвращает список кортежей: (source_address, url)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"CSV файл со ссылками не найден: {file_path}")

    pairs: List[Tuple[str, str]] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):
                source_address = row.get('source_address', '').strip()
                url = row.get('url', '').strip()
                
                # Пропускаем строки upd_ и пустые
                if source_address and url and not source_address.startswith('upd_'):
                    pairs.append((source_address, url))
                elif source_address.startswith('upd_'):
                    print(f"⏭️  Пропущена строка обновления: {source_address}")
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV файла: {e}", file=sys.stderr)
        raise
    
    return pairs


def save_screenshot_log(project_name: str, log_data: list) -> None:
    """Сохраняет лог скриншотов в CSV файл"""
    database_dir = get_project_database_dir(project_name)
    log_file = database_dir / f"osnovateli_doc_{project_name}_screenshot_log.csv"
    
    # Создаем директорию если не существует
    database_dir.mkdir(parents=True, exist_ok=True)
    
    # Определяем, нужно ли писать заголовки
    file_exists = log_file.exists()
    
    with log_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp', 'source_address', 'url', 'filename', 'status', 'error'])
        
        if not file_exists:
            writer.writeheader()
        
        for data in log_data:
            writer.writerow(data)


def disable_interactive_elements(page) -> None:
    """Отключает интерактивные элементы на странице перед скриншотом"""
    disable_script = """
    (function() {
        // Отключаем все кнопки
        document.querySelectorAll('button, input[type="button"], input[type="submit"]').forEach(el => {
            el.style.pointerEvents = 'none';
            el.style.opacity = '0.7';
        });
        
        // Отключаем все ссылки
        document.querySelectorAll('a').forEach(el => {
            el.style.pointerEvents = 'none';
            el.style.cursor = 'default';
        });
        
        // Отключаем все формы
        document.querySelectorAll('form').forEach(el => {
            el.style.pointerEvents = 'none';
        });
        
        // Останавливаем и скрываем все видео
        document.querySelectorAll('video').forEach(el => {
            el.pause();
            el.style.pointerEvents = 'none';
        });
        
        // Останавливаем и скрываем все аудио
        document.querySelectorAll('audio').forEach(el => {
            el.pause();
            el.style.pointerEvents = 'none';
        });
        
        // Отключаем iframe
        document.querySelectorAll('iframe').forEach(el => {
            el.style.pointerEvents = 'none';
        });
        
        // Закрываем модальные окна
        document.querySelectorAll('[class*="modal"], [class*="popup"], [class*="dialog"]').forEach(el => {
            el.style.display = 'none';
        });
        
        // Отключаем анимации через CSS
        const style = document.createElement('style');
        style.textContent = `
            *, *::before, *::after {
                animation-duration: 0s !important;
                animation-delay: 0s !important;
                transition-duration: 0s !important;
                transition-delay: 0s !important;
            }
        `;
        document.head.appendChild(style);
        
        // Отключаем все интерактивные элементы через pointer-events
        document.body.style.pointerEvents = 'auto';
        document.querySelectorAll('*').forEach(el => {
            const tag = el.tagName.toLowerCase();
            if (['button', 'a', 'input', 'select', 'textarea', 'video', 'audio', 'iframe'].includes(tag)) {
                el.style.pointerEvents = 'none';
            }
        });
    })();
    """
    try:
        page.evaluate(disable_script)
    except Exception:
        pass


def take_screenshot(page, url: str, output_path: Path, timeout: int = 15000) -> tuple[bool, str]:
    """Делает скриншот страницы. Возвращает (успех, сообщение об ошибке)"""
    try:
        # Быстрая стратегия: просто ждем базовой загрузки DOM
        page.goto(url, wait_until='domcontentloaded', timeout=timeout)
        
        # Пауза для рендеринга (5 сек для медленного интернета)
        time.sleep(5)
        
        # Отключаем интерактивные элементы перед скриншотом
        disable_interactive_elements(page)
        
        # Небольшая пауза после отключения элементов
        time.sleep(0.5)
        
        # Делаем скриншот всей страницы
        page.screenshot(path=str(output_path), full_page=True, timeout=10000)
        
        return True, ""
    except PlaywrightTimeout:
        return False, "Timeout при загрузке"
    except Exception as e:
        return False, str(e)


def process_screenshots(project_name: str, max_links: int = None, headless: bool = True) -> None:
    """Основная функция обработки скриншотов"""
    print(f"\n=== СОЗДАНИЕ СКРИНШОТОВ ИЗ OTHER_LINKS ===")
    print(f"Проект: {project_name}")
    
    # Получаем пути
    csv_file = get_other_links_csv_path(project_name)
    screenshots_dir = get_project_screenshots_dir(project_name)
    
    print(f"CSV файл: {csv_file}")
    print(f"Директория для скриншотов: {screenshots_dir}")
    
    # Проверяем существование CSV файла
    if not csv_file.exists():
        print(f"❌ CSV файл не найден: {csv_file}")
        print("Сначала запустите скрипт 1_parse_links.py")
        return
    
    # Создаем директорию для скриншотов
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    
    # Читаем ссылки
    try:
        pairs = read_links_from_csv(csv_file)
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV: {e}")
        return
    
    if not pairs:
        print("❌ CSV файл пуст или не содержит корректных ссылок")
        return
    
    # Ограничиваем количество для тестирования
    if max_links:
        pairs = pairs[:max_links]
        print(f"🧪 ТЕСТОВЫЙ РЕЖИМ: обработка первых {max_links} ссылок")
    
    print(f"\n📊 Всего ссылок для обработки: {len(pairs)}")
    
    # Список для лога
    log_data = []
    manual_screenshots = []  # Ссылки для ручной обработки
    successful = 0
    failed = 0
    
    # Запускаем Playwright
    print(f"\n🚀 Запуск браузера...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        # Настраиваем контекст браузера с реалистичным user agent
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU',
            timezone_id='Europe/Moscow'
        )
        
        page = context.new_page()
        
        # Обрабатываем каждую ссылку
        for idx, (source_address, url) in enumerate(pairs, 1):
            print(f"[{idx}/{len(pairs)}] 🔍 {source_address}: {url[:60]}...")
            
            # Формируем имя файла
            filename = f"{source_address}_screenshot.png"
            output_path = screenshots_dir / filename
            
            # Проверяем, не существует ли уже скриншот
            if output_path.exists():
                print(f"  ⏭️  Уже есть")
                continue
            
            # Делаем скриншот
            success, error_msg = take_screenshot(page, url, output_path)
            
            if success:
                print(f"  ✅ OK")
                log_data.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source_address': source_address,
                    'url': url,
                    'filename': filename,
                    'status': 'SUCCESS',
                    'error': ''
                })
                successful += 1
            else:
                print(f"  ❌ Fail: {error_msg}")
                # Добавляем в список для ручной обработки
                manual_screenshots.append(f"{source_address}\t{url}")
                
                log_data.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source_address': source_address,
                    'url': url,
                    'filename': '',
                    'status': 'FAILED',
                    'error': error_msg
                })
                failed += 1
            
            # Минимальная задержка между запросами (0.5-1 сек)
            if idx < len(pairs):
                time.sleep(random.uniform(0.5, 1))
        
        # Закрываем браузер
        browser.close()
    
    # Сохраняем лог
    if log_data:
        save_screenshot_log(project_name, log_data)
        print(f"\n📝 Лог сохранен в CSV файл")
    
    # Сохраняем список ссылок для ручной обработки
    if manual_screenshots:
        database_dir = get_project_database_dir(project_name)
        manual_file = database_dir / "manual_screenshots.txt"
        with manual_file.open('w', encoding='utf-8') as f:
            f.write("# Ссылки, которые не удалось скачать автоматически\n")
            f.write("# Формат: source_address<TAB>url\n\n")
            for line in manual_screenshots:
                f.write(line + '\n')
        print(f"📋 Список для ручной обработки: {manual_file}")
        print(f"   Количество: {len(manual_screenshots)}")
    
    # Итоговая статистика
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✅ Успешно: {successful}")
    print(f"❌ Ошибок: {failed}")
    print(f"📁 Скриншоты сохранены в: {screenshots_dir}")
    
    if failed > 0:
        print(f"\n💡 Совет: Для неудачных ссылок попробуйте:")
        print(f"   1. Открыть их вручную из manual_screenshots.txt")
        print(f"   2. Запустить скрипт повторно с --headed для отладки")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Создание скриншотов веб-страниц из other_links.csv"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Название проекта (если не указано, будет запрошено интерактивно)",
    )
    parser.add_argument(
        "--test",
        type=int,
        default=None,
        metavar="N",
        help="Тестовый режим: обработать только первые N ссылок",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Показывать окно браузера (полезно для отладки)",
    )
    
    args = parser.parse_args()
    
    project_name = args.project
    if project_name is None:
        project_name = get_project_name()
    
    headless = not args.headed
    
    process_screenshots(project_name, max_links=args.test, headless=headless)


if __name__ == "__main__":
    main()

