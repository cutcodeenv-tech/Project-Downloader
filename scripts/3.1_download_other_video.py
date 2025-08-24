import os
import yt_dlp
import yt_dlp.utils
import requests
import re
import urllib.parse
import json
import time
import subprocess
import sys
from datetime import datetime

def check_and_install_dependencies():
    """Проверяет и устанавливает необходимые зависимости"""
    print("=== ПРОВЕРКА ЗАВИСИМОСТЕЙ ===")
    
    required_packages = {
        'yt_dlp': 'yt-dlp',
        'requests': 'requests'
    }
    
    missing_packages = []
    
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
                print(f"Устанавливаю {package_name}...")
                subprocess.check_call(['brew', 'install', 'python-' + pip_name])
                print(f"✓ {package_name} успешно установлен")
            except subprocess.CalledProcessError as e:
                print(f"❌ Ошибка при установке {package_name}: {e}")
                return False
    
    print("✓ Все зависимости готовы\n")
    return True

def update_yt_dlp():
    """Обновляет yt-dlp до последней версии"""
    print("=== ОБНОВЛЕНИЕ YT-DLP ===")
    try:
        print("Обновляю yt-dlp...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
        print("✓ yt-dlp успешно обновлен")
        
        # Добавляем путь к yt-dlp в PATH
        user_bin_path = os.path.expanduser('~/Library/Python/3.9/bin')
        if user_bin_path not in os.environ.get('PATH', ''):
            os.environ['PATH'] = user_bin_path + ':' + os.environ.get('PATH', '')
            print(f"✓ Добавлен путь к yt-dlp в PATH: {user_bin_path}")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при обновлении yt-dlp: {e}")
        return False

def check_tor_connection(port=9150):
    """Проверяет подключение к Tor"""
    try:
        import requests
        proxies = {
            'http': f'socks5h://127.0.0.1:{port}',
            'https': f'socks5h://127.0.0.1:{port}'
        }
        
        response = requests.get('https://check.torproject.org/', proxies=proxies, timeout=15)
        if 'Congratulations' in response.text:
            print(f"✓ Tor работает на порту {port}")
            return True
        else:
            print(f"❌ Tor не работает на порту {port}")
            return False
    except Exception as e:
        print(f"❌ Ошибка подключения к Tor на порту {port}: {e}")
        return False

def configure_system_tor():
    """Настраивает системный Tor для работы с SOCKS прокси"""
    try:
        torrc_path = '/usr/local/etc/tor/torrc'
        torrc_content = """SocksPort 9050
DataDirectory /usr/local/var/lib/tor
"""
        
        # Создаем директорию если не существует
        os.makedirs('/usr/local/etc/tor', exist_ok=True)
        
        # Записываем конфигурацию
        with open(torrc_path, 'w') as f:
            f.write(torrc_content)
        
        print("✓ Конфигурация Tor создана")
        return True
    except Exception as e:
        print(f"❌ Ошибка при настройке Tor: {e}")
        return False

def start_tor():
    """Запускает Tor и проверяет его работу"""
    print("=== ПРОВЕРКА TOR ===")
    
    # Проверяем, запущен ли Tor на порту 9150
    if check_tor_connection(9150):
        return 9150
    
    # Проверяем, запущен ли Tor на порту 9050
    if check_tor_connection(9050):
        return 9050
    
    # Пытаемся запустить Tor Browser
    print("Tor не запущен. Пытаюсь запустить Tor Browser...")
    
    # Пути к Tor Browser на macOS
    tor_paths = [
        '/Applications/Tor Browser.app/Contents/MacOS/firefox',
        os.path.expanduser('~/Applications/Tor Browser.app/Contents/MacOS/firefox'),
        '/Applications/Tor Browser.app/Contents/MacOS/tor'
    ]
    
    for tor_path in tor_paths:
        if os.path.exists(tor_path):
            try:
                print(f"Запускаю Tor Browser: {tor_path}")
                subprocess.Popen([tor_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Ждем запуска Tor
                print("Ждем запуска Tor...")
                for i in range(30):  # Ждем до 30 секунд
                    time.sleep(1)
                    if check_tor_connection(9150):
                        print("✓ Tor Browser успешно запущен")
                        return 9150
                    if check_tor_connection(9050):
                        print("✓ Tor Browser успешно запущен")
                        return 9050
                
                print("❌ Tor Browser не запустился в течение 30 секунд")
                break
                
            except Exception as e:
                print(f"❌ Ошибка при запуске Tor Browser: {e}")
                continue
    
    # Пытаемся запустить системный Tor
    print("Пытаюсь запустить системный Tor...")
    try:
        # Настраиваем Tor конфигурацию
        if configure_system_tor():
            # Перезапускаем Tor сервис
            subprocess.check_call(['brew', 'services', 'restart', 'tor'])
            time.sleep(10)  # Ждем запуска
            
            if check_tor_connection(9050):
                print("✓ Системный Tor успешно запущен")
                return 9050
            else:
                print("❌ Системный Tor не запустился")
        else:
            print("❌ Не удалось настроить Tor")
            
    except subprocess.CalledProcessError:
        print("❌ Не удалось запустить системный Tor")
    
    return None

def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def get_platform_info(url):
    """Определяет платформу видео и возвращает информацию о ней"""
    # Специальная проверка для Yandex видео
    if 'yandex.ru/video' in url:
        return 'Yandex Video'
    
    # Специальная проверка для Megabook видео
    if 'megabook.ru/stream' in url:
        return 'Megabook Video'
    
    # Специальная проверка для Dzen видео
    if 'dzen.ru' in url and ('video' in url or 'media' in url):
        return 'Dzen Video'
    
    platform_info = {
        'youtube.com': 'YouTube',
        'youtu.be': 'YouTube',
        'vimeo.com': 'Vimeo',
        'dailymotion.com': 'Dailymotion',
        'twitch.tv': 'Twitch',
        'facebook.com': 'Facebook',
        'instagram.com': 'Instagram',
        'tiktok.com': 'TikTok',
        'reddit.com': 'Reddit',
        'twitter.com': 'Twitter/X',
        'x.com': 'Twitter/X',
        'bilibili.com': 'Bilibili',
        'rutube.ru': 'Rutube',
        'vk.com': 'VKontakte',
        'ok.ru': 'Odnoklassniki',
        'mail.ru': 'Mail.ru',
        'yandex.ru': 'Yandex',
        'pinterest.com': 'Pinterest',
        'linkedin.com': 'LinkedIn',
        'snapchat.com': 'Snapchat',
        'telegram.org': 'Telegram',
        'discord.com': 'Discord',
        'zoom.us': 'Zoom',
        'teams.microsoft.com': 'Microsoft Teams',
        'webex.com': 'Cisco Webex',
        'kick.com': 'Kick',
        'rumble.com': 'Rumble',
        'odysee.com': 'Odysee',
        'lbry.tv': 'LBRY',
        'peertube.fr': 'PeerTube',
        'peertube.org': 'PeerTube',
        'invidious.io': 'Invidious',
        'invidious.snopyta.org': 'Invidious',
        'nicovideo.jp': 'Niconico',
        'niconico.jp': 'Niconico',
        'youku.com': 'Youku',
        'iqiyi.com': 'iQiyi',
        'tencent.com': 'Tencent',
        'qq.com': 'QQ',
        'weibo.com': 'Weibo',
        'douyin.com': 'Douyin',
        'dzen.ru': 'Dzen',
        'megabook.ru': 'Megabook'
    }
    
    for domain, platform in platform_info.items():
        if domain in url:
            return platform
    return 'Unknown Platform'

def is_video_url(url):
    """Проверяет, является ли ссылка видео ссылкой"""
    # Специальная проверка для Yandex видео
    if 'yandex.ru/video' in url:
        return True
    
    # Специальная проверка для Megabook видео
    if 'megabook.ru/stream' in url:
        return True
    
    # Специальная проверка для Dzen видео
    if 'dzen.ru' in url and ('video' in url or 'media' in url):
        return True
    
    # Расширенная проверка для различных видео платформ
    video_domains = [
        # Основные видео платформы
        'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 
        'twitch.tv', 'facebook.com', 'instagram.com', 'tiktok.com',
        'reddit.com', 'twitter.com', 'x.com', 'bilibili.com',
        
        # Дополнительные платформы
        'rutube.ru', 'vk.com', 'ok.ru', 'mail.ru', 'yandex.ru',
        'pinterest.com', 'linkedin.com', 'snapchat.com', 'telegram.org',
        'discord.com', 'zoom.us', 'teams.microsoft.com', 'webex.com',
        
        # Стриминговые платформы
        'kick.com', 'rumble.com', 'odysee.com', 'lbry.tv',
        'peertube.fr', 'peertube.org', 'invidious.io', 'invidious.snopyta.org',
        
        # Азиатские платформы
        'nicovideo.jp', 'niconico.jp', 'youku.com', 'iqiyi.com',
        'tencent.com', 'qq.com', 'weibo.com', 'douyin.com',
        
        # Российские платформы
        'dzen.ru', 'megabook.ru'
    ]
    return any(domain in url for domain in video_domains)

def get_video_title(url):
    """Получает название видео"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title', 'Unknown Title')
    except Exception as e:
        print(f"  ⚠️  Не удалось получить название видео: {e}")
        return 'Unknown Title'

def sanitize_filename(filename):
    """Очищает имя файла от недопустимых символов"""
    # Заменяем недопустимые символы на подчеркивание
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Убираем лишние пробелы и подчеркивания
    filename = re.sub(r'\s+', '_', filename)
    filename = re.sub(r'_+', '_', filename)
    
    return filename.strip('_')

def download_video(url, display_name, download_dir, error_file_path, tor_port=None):
    """Скачивает видео"""
    try:
        print(f"Скачиваю: {display_name}")
        
        # Определяем платформу
        platform = get_platform_info(url)
        print(f"  🌐 Платформа: {platform}")
        
        # Получаем название видео
        video_title = get_video_title(url)
        print(f"  📺 Название видео: {video_title}")
        
        # Создаем имя файла: {display_name}_{video_title}
        safe_video_title = sanitize_filename(video_title)
        filename_template = f"{display_name}_{safe_video_title}.%(ext)s"
        
        # Настройки для yt-dlp с поддержкой различных платформ
        ydl_opts = {
            'outtmpl': os.path.join(download_dir, filename_template),
            'concurrent_fragment_downloads': 8,
            'fragment_retries': 10,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_retries': 3,
            'ignoreerrors': False,
            'no_warnings': False,
            'verbose': True,
        }
        
        # Добавляем cookies файл, если он существует
        cookies_file = os.path.join(os.path.dirname(os.path.dirname(download_dir)), 'cookies.txt')
        if os.path.exists(cookies_file):
            ydl_opts['cookiefile'] = cookies_file
            print(f"  🍪 Использую cookies файл: {cookies_file}")
        
        # Добавляем Tor прокси для обхода блокировок (если доступен)
        if tor_port:
            TOR_PROXY = f'socks5h://127.0.0.1:{tor_port}'
            ydl_opts['proxy'] = TOR_PROXY
            print(f"  🔗 Использую Tor прокси: {TOR_PROXY}")
        else:
            print(f"  ⚠️  Скачиваю без Tor прокси")
        
        # Специальные настройки для разных платформ
        if 'yandex.ru' in url:
            # Для Yandex видео добавляем дополнительные заголовки
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            print(f"  🔧 Применяю специальные настройки для Yandex")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            print(f"  ✓ Видео успешно скачано")
            return True, video_title
            
        except yt_dlp.utils.DownloadError as e:
            # Если не удалось скачать, пробуем без Tor
            if tor_port:
                print(f"  🔄 Повторная попытка без Tor прокси...")
                ydl_opts.pop('proxy', None)
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    print(f"  ✓ Видео успешно скачано (без Tor)")
                    return True, video_title
                except Exception as e2:
                    print(f"  ❌ Ошибка при повторной попытке: {e2}")
                    raise e2
            else:
                raise e
        
    except Exception as e:
        error_msg = str(e)
        print(f"  ❌ Ошибка при скачивании: {error_msg}")
        
        # Логируем ошибку
        log_video_error(display_name, url, video_title, error_file_path)
        return False, video_title

def read_video_links(video_links_file):
    """Читает ссылки на видео из файла"""
    links = []
    
    try:
        with open(video_links_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            
            # Парсим строку формата "A1 1 : https://example.com/..."
            parts = line.strip().split(' : ', 1)
            if len(parts) == 2:
                display_name = parts[0].strip()
                url = parts[1].strip()
                
                # Проверяем, что это видео ссылка
                if is_video_url(url):
                    links.append({
                        'display_name': display_name,
                        'url': url
                    })
                else:
                    print(f"⚠️  Пропускаю не-видео ссылку: {url}")
        
        return links
        
    except FileNotFoundError:
        print(f"❌ Файл {video_links_file} не найден!")
        return []
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {video_links_file}: {e}")
        return []

def log_video_error(display_name, url, video_title, error_file_path):
    """Логирует ошибки скачивания видео в файл"""
    try:
        with open(error_file_path, 'a', encoding='utf-8') as f:
            f.write(f"{display_name} : {url} : {video_title}\n")
    except Exception as e:
        print(f"Ошибка при записи в файл ошибок: {e}")

def create_pull_video_links(error_file_path, video_dir):
    """Создает файл pull_video_links.txt на основе ошибок скачивания"""
    try:
        if not os.path.exists(error_file_path):
            print("Файл с ошибками не найден, пропускаю создание pull_video_links.txt")
            return
        
        pull_video_file = os.path.join(video_dir, 'pull_video_links.txt')
        
        with open(error_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        video_links = []
        for line in lines:
            if line.strip():
                # Парсим строку формата "display_name : url : video_title"
                parts = line.strip().split(' : ', 2)
                if len(parts) >= 2:
                    url = parts[1].strip()
                    if is_video_url(url):
                        video_links.append(url)
        
        if video_links:
            with open(pull_video_file, 'w', encoding='utf-8') as f:
                for url in video_links:
                    f.write(f"{url}\n")
            
            print(f"✓ Создан файл pull_video_links.txt с {len(video_links)} ссылками")
        else:
            print("В файле ошибок не найдено видео ссылок")
            
    except Exception as e:
        print(f"❌ Ошибка при создании pull_video_links.txt: {e}")

def main():
    print("=== СКРИПТ СКАЧИВАНИЯ ДРУГИХ ВИДЕО ===")
    
    # Проверяем и устанавливаем зависимости
    if not check_and_install_dependencies():
        print("❌ Не удалось установить необходимые зависимости!")
        return
    
    # Обновляем yt-dlp
    if not update_yt_dlp():
        print("❌ Не удалось обновить yt-dlp!")
        return
    
    # Запускаем и проверяем Tor
    tor_port = start_tor()
    if tor_port is None:
        print("⚠️  Не удалось запустить Tor. Продолжаю без Tor прокси.")
        tor_port = None
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Создаем структуру директорий
    downloads_dir = os.path.expanduser('~/Downloads')
    download_all_dir = os.path.join(downloads_dir, 'download_all')
    project_dir = os.path.join(download_all_dir, project_name)
    parse_links_dir = os.path.join(project_dir, '1_parse_links')
    video_dir = os.path.join(project_dir, '3.1_other_video')
    
    # Проверяем существование директории с ссылками
    if not os.path.exists(parse_links_dir):
        print(f"❌ Директория {parse_links_dir} не найдена!")
        print("Сначала запустите скрипт 1_parse_links.py")
        return
    
    # Создаем директорию для видео
    os.makedirs(video_dir, exist_ok=True)
    
    # Путь к файлу с ссылками на видео
    video_links_file = os.path.join(parse_links_dir, 'video_links.txt')
    
    # Путь к файлу ошибок
    error_file_path = os.path.join(video_dir, 'video_download_errors.txt')
    
    # Очищаем файл ошибок
    if os.path.exists(error_file_path):
        os.remove(error_file_path)
    
    print(f"\n=== СКАЧИВАНИЕ ДРУГИХ ВИДЕО ===")
    print(f"Проект: {project_name}")
    print(f"Директория видео: {video_dir}")
    print(f"Файл с ссылками: {video_links_file}")
    if tor_port:
        print("Видео будут скачиваться через Tor для обхода блокировок")
    else:
        print("Видео будут скачиваться напрямую (без Tor)")
    
    # Читаем ссылки на видео
    video_links = read_video_links(video_links_file)
    
    if not video_links:
        print("❌ Не найдено ссылок на видео для скачивания!")
        return
    
    print(f"\nНайдено {len(video_links)} ссылок на видео")
    
    # Скачиваем видео
    successful_downloads = 0
    failed_downloads = 0
    
    for i, link_info in enumerate(video_links, 1):
        print(f"\n[{i}/{len(video_links)}] Обрабатываю: {link_info['display_name']}")
        
        success, video_title = download_video(
            link_info['url'], 
            link_info['display_name'], 
            video_dir, 
            error_file_path,
            tor_port
        )
        
        if success:
            successful_downloads += 1
        else:
            failed_downloads += 1
        
        # Небольшая пауза между запросами
        time.sleep(1)
    
    print(f"\n=== РЕЗУЛЬТАТЫ СКАЧИВАНИЯ ===")
    print(f"Успешно скачано: {successful_downloads}")
    print(f"Ошибок скачивания: {failed_downloads}")
    print(f"Всего обработано: {len(video_links)}")
    
    if failed_downloads > 0:
        print(f"\nОшибки сохранены в файл: {error_file_path}")
    
    # Создаем файл pull_video_links.txt на основе ошибок
    create_pull_video_links(error_file_path, video_dir)
    
    print(f"\nВидео сохранены в: {video_dir}")

if __name__ == "__main__":
    main()
