#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Парсер названий каналов для YouTube ссылок из CSV файлов проекта.

Функционал:
- запрашивает название проекта,
- ищет CSV файл youtube_links.csv в базе данных проекта,
- извлекает названия каналов для каждой YouTube ссылки через oEmbed API,
- создает новый CSV файл с индексом, ссылкой и названием канала.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests


DEFAULT_SETTINGS = {
    "sleep_seconds": 0.12,
    "force_refresh": False,
}

REQUEST_TIMEOUT = 20
SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}


class Logger:
    """Класс для логирования в консоль в реальном времени"""
    
    def __init__(self):
        self.error_count = 0
        self.success_count = 0
        self.cache_hits = 0
        self.stats = {
            "youtube": {"success": 0, "error": 0},
            "unknown_host": 0,
            "empty_host": 0,
            "http_errors": 0,
            "timeout_errors": 0,
            "parse_errors": 0,
        }
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] === Начало обработки YouTube каналов ===\n")
    
    def _write(self, level: str, message: str, details: Optional[str] = None):
        """Выводит сообщение в консоль"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_colors = {
            "INFO": "\033[36m",    # Cyan
            "ERROR": "\033[31m",   # Red
            "WARN": "\033[33m",    # Yellow
            "SUCCESS": "\033[32m", # Green
            "DEBUG": "\033[90m",   # Dark gray
        }
        reset = "\033[0m"
        color = level_colors.get(level, "")
        
        log_line = f"{color}[{timestamp}] [{level}]{reset} {message}"
        if details:
            log_line += f"\n  → {details}"
        
        print(log_line)
        sys.stdout.flush()  # Принудительный вывод в реальном времени
    
    def info(self, message: str, details: Optional[str] = None):
        """Информационное сообщение"""
        self._write("INFO", message, details)
    
    def error(self, message: str, details: Optional[str] = None, exception: Optional[Exception] = None):
        """Сообщение об ошибке"""
        self.error_count += 1
        error_details = details or ""
        if exception:
            error_details += f"\n  Исключение: {type(exception).__name__}: {str(exception)}"
            error_details += f"\n  Traceback:\n{''.join(traceback.format_tb(exception.__traceback__))}"
        self._write("ERROR", message, error_details)
    
    def warning(self, message: str, details: Optional[str] = None):
        """Предупреждение"""
        self._write("WARN", message, details)
    
    def success(self, message: str, details: Optional[str] = None):
        """Успешная операция"""
        self.success_count += 1
        self._write("SUCCESS", message, details)
    
    def debug(self, message: str, details: Optional[str] = None):
        """Отладочное сообщение"""
        self._write("DEBUG", message, details)
    
    def print_stats(self):
        """Выводит статистику"""
        print("\n" + "=" * 80)
        print("=== Статистика обработки ===")
        print(f"Успешно обработано: {self.success_count}")
        print(f"Ошибок: {self.error_count}")
        print(f"Попаданий в кеш: {self.cache_hits}")
        print("Статистика по типам:")
        for key, value in self.stats.items():
            if isinstance(value, dict):
                print(f"  {key}: успешно={value['success']}, ошибок={value['error']}")
            else:
                print(f"  {key}: {value}")
        print("=" * 80)


def get_project_name() -> str:
    """Запрашивает название проекта у пользователя"""
    while True:
        name = input("Введите название проекта: ").strip()
        if name:
            return name
        print("Ошибка: название проекта не может быть пустым.")


def get_project_database_dir(project_name: str) -> str:
    """Возвращает путь к директории database проекта"""
    data_dir = "/Users/theseus/Projects/osnovateli_doc_framework/data"
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, "database")
    return database_dir


def read_links_from_csv(csv_file: str) -> List[Tuple[str, str]]:
    """Читает ссылки из CSV файла.
    
    Ожидаемый формат CSV:
    source_address,url
    B3_1,https://www.youtube.com/watch?v=...
    
    Возвращает список кортежей: (source_address, url)
    """
    if not os.path.exists(csv_file):
        raise FileNotFoundError(f"CSV файл не найден: {csv_file}")

    links: List[Tuple[str, str]] = []
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_address = row.get("source_address", "").strip()
                url = row.get("url", "").strip()

                # Пропускаем строки upd_ и пустые
                if source_address and url and not source_address.startswith("upd_"):
                    links.append((source_address, url))
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}")
        raise

    return links


def find_youtube_links_csv(database_dir: str, project_name: str) -> Optional[str]:
    """Ищет CSV файл с YouTube ссылками проекта"""
    csv_file = os.path.join(database_dir, f"osnovateli_doc_{project_name}_youtube_links.csv")
    if os.path.exists(csv_file):
        return csv_file
    return None


def fetch_json(session: requests.Session, url: str, logger: Optional[Logger] = None) -> Optional[dict]:
    """Получает JSON данные по URL"""
    try:
        if logger:
            logger.debug(f"Запрос JSON: {url}")
        response = session.get(url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code >= 400:
            if logger:
                logger.warning(f"HTTP ошибка {response.status_code} при запросе JSON", f"URL: {url}")
            return None
        try:
            data = response.json()
            if logger:
                logger.debug(f"JSON получен успешно: {url}")
            return data
        except json.JSONDecodeError as e:
            if logger:
                logger.error(f"Ошибка парсинга JSON", f"URL: {url}, Ответ: {response.text[:200]}", e)
            return None
    except requests.exceptions.Timeout as e:
        if logger:
            logger.error(f"Таймаут при запросе JSON", f"URL: {url}", e)
        return None
    except requests.exceptions.RequestException as e:
        if logger:
            logger.error(f"Ошибка запроса JSON", f"URL: {url}", e)
        return None
    except Exception as e:
        if logger:
            logger.error(f"Неожиданная ошибка при запросе JSON", f"URL: {url}", e)
        return None


def fetch_html(session: requests.Session, url: str, logger: Optional[Logger] = None) -> str:
    """Получает HTML содержимое по URL"""
    try:
        if logger:
            logger.debug(f"Запрос HTML: {url}")
        response = session.get(
            url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
        )
        response.raise_for_status()
        if logger:
            logger.debug(f"HTML получен успешно: {url}, размер: {len(response.text)} байт")
        return response.text
    except requests.exceptions.Timeout as e:
        if logger:
            logger.error(f"Таймаут при запросе HTML", f"URL: {url}", e)
        raise
    except requests.exceptions.HTTPError as e:
        if logger:
            logger.error(f"HTTP ошибка при запросе HTML", f"URL: {url}, Статус: {e.response.status_code if hasattr(e, 'response') else 'unknown'}", e)
        raise
    except requests.exceptions.RequestException as e:
        if logger:
            logger.error(f"Ошибка запроса HTML", f"URL: {url}", e)
        raise
    except Exception as e:
        if logger:
            logger.error(f"Неожиданная ошибка при запросе HTML", f"URL: {url}", e)
        raise


def parse_author_from_html(html: str) -> str:
    """Извлекает автора/канал из HTML мета-тегов"""
    if not html:
        return ""
    match = re.search(
        r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    raw = re.sub(r"\s+", " ", match.group(1)).strip()
    return raw


def parse_host(url: str) -> Tuple[str, str]:
    """Парсит хост из URL"""
    try:
        match = re.match(r"^https?://([^/]+)(/.*)?", url, flags=re.IGNORECASE)
        host = match.group(1).lower().replace("www.", "") if match else ""
        path = match.group(2).lower() if match and match.group(2) else ""
        return host, path
    except Exception:
        return "", ""


def get_channel_for_url(session: requests.Session, url: str, logger: Optional[Logger] = None) -> str:
    """Получает название канала для YouTube URL через oEmbed API"""
    host, _ = parse_host(url)
    if not host:
        if logger:
            logger.warning(f"Не удалось определить хост", f"URL: {url}")
            logger.stats["empty_host"] += 1
        return ""
    
    # Проверяем, что это YouTube ссылка
    if "youtube.com" not in host and host != "youtu.be":
        if logger:
            logger.warning(f"Не YouTube ссылка, пропуск", f"URL: {url}, Хост: {host}")
            logger.stats["unknown_host"] += 1
        return ""
    
    if logger:
        logger.info(f"Обработка YouTube URL", f"URL: {url}")
    
    try:
        # Используем YouTube oEmbed API
        oembed_url = "https://www.youtube.com/oembed?format=json&url=" + requests.utils.quote(
            url, safe=""
        )
        payload = fetch_json(session, oembed_url, logger)
        if payload:
            if payload.get("author_name"):
                channel = str(payload["author_name"]).strip()
                if logger:
                    logger.success(f"Канал найден через YouTube oEmbed", f"URL: {url}, Канал: {channel}")
                    logger.stats["youtube"]["success"] += 1
                return channel
            else:
                if logger:
                    logger.warning(f"В ответе YouTube oEmbed нет author_name", f"URL: {url}, Ответ: {json.dumps(payload)[:200]}")
                    logger.stats["youtube"]["error"] += 1
        else:
            if logger:
                logger.warning(f"Не удалось получить данные от YouTube oEmbed", f"URL: {url}")
                logger.stats["youtube"]["error"] += 1
        return ""
    except Exception as e:
        if logger:
            logger.error(f"Неожиданная ошибка при обработке YouTube URL", f"URL: {url}", e)
        return ""


def process_links(
    links: List[Tuple[str, str]],
    sleep_seconds: float,
    force_refresh: bool,
    cache: Dict[str, str],
    logger: Optional[Logger] = None,
) -> List[Tuple[str, str, str]]:
    """Обрабатывает ссылки и получает названия каналов"""
    session = requests.Session()
    processed = 0
    start_time = time.time()
    results: List[Tuple[str, str, str]] = []
    total_links = len(links)

    if logger:
        logger.info(f"Начало обработки ссылок", f"Всего ссылок: {total_links}")

    for idx, (source_address, url) in enumerate(links, start=1):
        if logger:
            logger.info(f"Обработка ссылки {idx}/{total_links}", f"Индекс: {source_address}, URL: {url}")

        # Проверяем кеш
        if url in cache and not force_refresh:
            channel = cache[url]
            if logger:
                logger.debug(f"Использован кеш", f"URL: {url}, Канал: {channel if channel else '(пусто)'}")
                logger.cache_hits += 1
            results.append((source_address, url, channel))
            continue

        # Получаем название канала
        if logger:
            logger.debug(f"Запрос канала для URL", f"URL: {url}")
        channel = get_channel_for_url(session, url, logger)
        cache[url] = channel
        
        if channel:
            if logger:
                logger.success(f"Канал получен", f"Индекс: {source_address}, URL: {url}, Канал: {channel}")
        else:
            if logger:
                logger.warning(f"Канал не найден", f"Индекс: {source_address}, URL: {url}")
        
        results.append((source_address, url, channel))
        processed += 1

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        if processed % 25 == 0:
            elapsed = time.time() - start_time
            if logger:
                logger.info(f"Прогресс обработки", f"Обработано: {processed}/{total_links}, Прошло времени: {elapsed:.1f} сек")
            else:
                print(f"Обработано ссылок: {processed}")

    # Для оставшихся ссылок используем кеш или пустые значения
    remaining = len(links) - len(results)
    if remaining > 0:
        if logger:
            logger.info(f"Обработка оставшихся ссылок из кеша", f"Осталось: {remaining}")
        for source_address, url in links[len(results):]:
            if url in cache:
                channel = cache[url]
                if logger:
                    logger.debug(f"Использован кеш для оставшейся ссылки", f"URL: {url}, Канал: {channel if channel else '(пусто)'}")
            else:
                channel = ""
                if logger:
                    logger.debug(f"Нет данных в кеше", f"URL: {url}")
            results.append((source_address, url, channel))

    if logger:
        logger.info(f"Обработка завершена", f"Всего обработано: {len(results)}, Новых запросов: {processed}")

    return results


def save_results_to_csv(
    results: List[Tuple[str, str, str]], output_file: str
) -> None:
    """Сохраняет результаты в CSV файл"""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_address", "url", "channel"])
        for source_address, url, channel in results:
            writer.writerow([source_address, url, channel])


def load_cache_from_csv(cache_file: str) -> Dict[str, str]:
    """Загружает кеш из CSV файла"""
    cache: Dict[str, str] = {}
    if not os.path.exists(cache_file):
        return cache

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("url", "").strip()
                channel = row.get("channel", "").strip()
                if url:
                    cache[url] = channel
    except Exception as e:
        print(f"Ошибка при чтении кеша: {e}")

    return cache


def save_cache_to_csv(cache: Dict[str, str], cache_file: str) -> None:
    """Сохраняет кеш в CSV файл"""
    if not cache:
        return

    os.makedirs(os.path.dirname(cache_file), exist_ok=True)

    with open(cache_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "channel"])
        for url, channel in cache.items():
            writer.writerow([url, channel])


def main() -> None:
    print("=== Парсер названий каналов для YouTube ссылок из CSV ===")

    # Запрашиваем название проекта
    project_name = get_project_name()

    # Получаем путь к директории database
    database_dir = get_project_database_dir(project_name)

    if not os.path.exists(database_dir):
        print(f"Ошибка: директория проекта не найдена: {database_dir}")
        print("Сначала запустите скрипт 0_structure.py для создания структуры проекта")
        sys.exit(1)

    # Ищем CSV файл с YouTube ссылками
    csv_file = find_youtube_links_csv(database_dir, project_name)
    if not csv_file:
        print(f"Ошибка: CSV файл с YouTube ссылками не найден в {database_dir}")
        print(f"Ожидается файл: osnovateli_doc_{project_name}_youtube_links.csv")
        print("Сначала запустите скрипт 1_parse_links.py для создания CSV файла")
        sys.exit(1)

    print(f"✓ Найден CSV файл: {os.path.basename(csv_file)}")

    # Читаем ссылки из CSV
    try:
        links = read_links_from_csv(csv_file)
        print(f"✓ Прочитано ссылок: {len(links)}")
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}")
        sys.exit(1)

    if not links:
        print("В CSV файле не найдено ссылок для обработки.")
        sys.exit(0)

    # Запрашиваем настройки
    print("\n=== Настройки обработки ===")
    sleep_seconds = float(
        input(
            f"Пауза между запросами, сек [{DEFAULT_SETTINGS['sleep_seconds']:.3f}]: "
        ).strip()
        or DEFAULT_SETTINGS["sleep_seconds"]
    )
    force_refresh_input = (
        input("Перезаписывать уже обработанные ссылки? (y/n) [n]: ").strip().lower()
    )
    force_refresh = force_refresh_input in {"y", "yes", "д", "да", "true", "1"}

    # Создаем логгер
    logger = Logger()
    logger.info(f"Инициализация скрипта", f"Проект: {project_name}, CSV файл: {os.path.basename(csv_file)}")

    # Загружаем кеш
    cache_file = os.path.join(database_dir, "channel_cache.csv")
    logger.info(f"Загрузка кеша", f"Файл: {os.path.basename(cache_file)}")
    cache = load_cache_from_csv(cache_file)
    logger.info(f"Кеш загружен", f"Записей в кеше: {len(cache)}")

    # Обрабатываем ссылки
    logger.info(f"Начало обработки ссылок", f"Всего ссылок: {len(links)}")
    results = process_links(
        links, sleep_seconds, force_refresh, cache, logger
    )

    # Сохраняем кеш
    logger.info(f"Сохранение кеша", f"Файл: {os.path.basename(cache_file)}")
    save_cache_to_csv(cache, cache_file)
    logger.info(f"Кеш сохранен", f"Записей в кеше: {len(cache)}")

    # Сохраняем результаты
    output_file = os.path.join(database_dir, f"osnovateli_doc_{project_name}_channels.csv")
    logger.info(f"Сохранение результатов", f"Файл: {os.path.basename(output_file)}")
    save_results_to_csv(results, output_file)
    logger.info(f"Результаты сохранены", f"Файл: {os.path.basename(output_file)}")

    # Статистика
    processed_count = sum(1 for _, _, channel in results if channel)
    empty_count = len(results) - processed_count

    logger.print_stats()

    print(f"\n=== Итог ===")
    print(f"Всего ссылок: {len(results)}")
    print(f"Обработано (найдено каналов): {processed_count}")
    print(f"Без канала: {empty_count}")
    print(f"Результаты сохранены в: {output_file}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Операция отменена пользователем.")
        sys.exit(1)
