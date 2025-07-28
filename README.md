# Download All - Скрипты для массовой загрузки медиафайлов

Набор скриптов для автоматической загрузки медиафайлов из Google таблиц с поддержкой YouTube, изображений, видео и новостных сайтов.

## Основные скрипты

### 1. `Download all_v1.03_tor.py` - Основной скрипт загрузки
- Загружает медиафайлы из указанной колонки Google таблицы
- Поддерживает YouTube, изображения, видео и новостные сайты
- Использует Tor для анонимности
- Сохраняет файлы в `~/Downloads/media_from_sheet/`

### 2. `download_youtube.py` - Специализированный скрипт для YouTube
- Загружает только YouTube видео из указанной колонки
- Автоматически устанавливает зависимости
- Сохраняет видео в `~/Downloads/youtube_videos/`

### 3. `sort_errors.py` - Анализ ошибок загрузки
- Анализирует файлы ошибок от основных скриптов
- Группирует неудачные ссылки по индексам
- Создает отчеты в `~/Downloads/sort_errors/`

## Быстрый старт

### 1. Установка зависимостей

```bash
bash install.sh
```

### 2. Настройка окружения

Создайте файл `.env` на основе `env.template`:

```bash
cp env.template .env
```

Заполните `.env` данными Google Service Account:
- `TYPE`, `PROJECT_ID`, `PRIVATE_KEY_ID`
- `PRIVATE_KEY`, `CLIENT_EMAIL`, `CLIENT_ID`
- `AUTH_URI`, `TOKEN_URI`, `AUTH_PROVIDER_X509_CERT_URL`
- `CLIENT_X509_CERT_URL`, `UNIVERSE_DOMAIN`

### 3. Запуск скриптов

**Основной скрипт:**
```bash
python3 "Download all_v1.03_tor.py"
```

**YouTube скрипт:**
```bash
python3 download_youtube.py
```

**Анализ ошибок:**
```bash
python3 sort_errors.py
```

## Как использовать

1. Запустите скрипт
2. Введите ссылку на Google таблицу
3. Укажите букву колонки (A, B, C, и т.д.)
4. Дождитесь завершения загрузки
5. Проверьте результаты в папке Downloads

## Файлы и папки

- `cookies.txt` - файл с cookies для авторизации
- `downloads/` - папка с файлами ошибок
- `scripts/` - дополнительные скрипты
- `install.sh` - автоматическая установка зависимостей
- `env.template` - шаблон для настройки окружения