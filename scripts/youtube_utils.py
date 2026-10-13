#!/usr/bin/env python3
"""Единый классификатор YouTube-ссылок для пайплайна скачивания.

Правила (общие для генерации списка, скачивания и переименования):
- канал (/@handle, /channel/.., /c/.., /user/..) — пропускаем;
- shorts — пропускаем;
- плейлист без конкретного видео — пропускаем;
- watch?v=ID&list=.. — берём только видео ID (list= отбрасывается);
- скачиваем только то, что youtube_url_kind() считает 'video'.
"""

import os
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

_VIDEO_ID_RE = re.compile(r'^[0-9A-Za-z_-]{11}$')


def is_shorts_url(url: str) -> bool:
    return '/shorts/' in (url or '').lower()


def clean_url(url: str) -> str:
    """Убирает list=/index= из URL, если есть конкретное видео (v=),
    чтобы не качать плейлист, а только указанное видео."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if 'v' in qs and 'list' in qs:
            qs.pop('list', None)
            qs.pop('index', None)
            return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    except Exception:
        pass
    return url


def extract_video_id(url: str) -> str:
    """ID видео (11 символов) или '' если ссылка не на конкретное видео."""
    u = (url or '').strip()
    if not u:
        return ''
    try:
        parsed = urlparse(u)
    except Exception:
        return ''
    host = (parsed.netloc or '').lower().replace('www.', '')
    path = parsed.path or ''
    qs = parse_qs(parsed.query)

    if host == 'youtu.be':
        candidate = path.strip('/').split('/')[0] if path else ''
        return candidate if _VIDEO_ID_RE.match(candidate) else ''

    v = (qs.get('v') or [''])[0]
    if _VIDEO_ID_RE.match(v):
        return v

    m = re.search(r'/(?:embed|v|shorts)/([0-9A-Za-z_-]{11})', path)
    if m:
        return m.group(1)
    return ''


def youtube_url_kind(url: str) -> str:
    """Возвращает 'video' | 'shorts' | 'channel' | 'playlist' | 'other'."""
    u = (url or '').strip()
    low = u.lower()
    if 'youtube.com' not in low and 'youtu.be' not in low:
        return 'other'
    if '/shorts/' in low:
        return 'shorts'
    try:
        parsed = urlparse(u)
    except Exception:
        return 'other'

    host = (parsed.netloc or '').lower().replace('www.', '')
    path = parsed.path or ''
    qs = parse_qs(parsed.query)

    # youtu.be/<id>
    if host == 'youtu.be':
        candidate = path.strip('/').split('/')[0] if path else ''
        return 'video' if _VIDEO_ID_RE.match(candidate) else 'other'

    # watch?v=<id>  (берётся даже если есть list= — это конкретное видео)
    v = (qs.get('v') or [''])[0]
    if _VIDEO_ID_RE.match(v):
        return 'video'

    # /embed/<id>, /v/<id>
    if re.search(r'/(?:embed|v)/[0-9A-Za-z_-]{11}', path):
        return 'video'

    # плейлист без конкретного видео
    if path.rstrip('/').endswith('/playlist') or 'list' in qs:
        return 'playlist'

    # канал
    if path.startswith('/@') or path.startswith('/channel/') \
            or path.startswith('/c/') or path.startswith('/user/'):
        return 'channel'

    return 'other'


def is_downloadable_youtube_video(url: str) -> bool:
    """True только для ссылок на конкретное видео (не канал/шортс/плейлист)."""
    return youtube_url_kind(url) == 'video'


# ── Таймкоды: скачивание фрагмента вместо целого видео ──────────────────────
#
# Источники таймкода:
#   1) диапазон в ячейке таблицы сразу после ссылки: «<ссылка> 1:35-2:10» —
#      parse_links превращает его в параметры ссылки t=95&end=130;
#   2) ?t=95 / &t=1m35s в самой ссылке (кнопка «Поделиться с таймкодом»).
#      Без конца диапазона длина фрагмента берётся из настройки
#      VIDEO_SECTION_SECONDS; 0 (по умолчанию) — качать видео целиком.

_TIMECODE_TEXT = r'\d{1,2}(?::\d{2}){1,2}'
_CELL_RANGE_RE = re.compile(
    rf'^\s*[(\[]?\s*({_TIMECODE_TEXT})\s*[-–—]\s*({_TIMECODE_TEXT})'
)


def parse_timecode(value) -> int | None:
    """'95', '95s', '1m35s', '1h2m3s', '1:35', '1:02:03' -> секунды."""
    text = str(value or '').strip().lower()
    if not text:
        return None
    if re.fullmatch(r'\d+', text):
        return int(text)
    if re.fullmatch(_TIMECODE_TEXT, text):
        seconds = 0
        for part in text.split(':'):
            seconds = seconds * 60 + int(part)
        return seconds
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', text)
    if m and any(m.groups()):
        h, mnt, sec = (int(g or 0) for g in m.groups())
        return h * 3600 + mnt * 60 + sec
    return None


def video_section(url: str) -> tuple[int, int] | None:
    """(start, end) в секундах, если ссылку нужно качать фрагментом."""
    try:
        qs = parse_qs(urlparse(url or '').query)
    except Exception:
        return None
    start = parse_timecode((qs.get('t') or qs.get('start') or [''])[0])
    if start is None:
        return None
    end = parse_timecode((qs.get('end') or [''])[0])
    if end is None:
        try:
            length = int(os.getenv('VIDEO_SECTION_SECONDS') or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return None
        end = start + length
    if end <= start:
        return None
    return start, end


def section_tag(section: tuple[int, int] | None) -> str:
    """Метка фрагмента в имени файла: '[t95-130]' ('' — видео целиком)."""
    return f'[t{section[0]}-{section[1]}]' if section else ''


def matches_section(filename: str, video_id: str, section: tuple[int, int] | None) -> bool:
    """Файл — это нужное видео и нужный фрагмент (или целое видео без метки)."""
    if not video_id or f'[{video_id}]' not in filename:
        return False
    tag = section_tag(section)
    if tag:
        return tag in filename
    return re.search(r'\[t\d+-\d+\]', filename) is None


def attach_cell_range(url: str, text_after_url: str) -> str:
    """Если сразу после YouTube-ссылки в ячейке стоит «1:35-2:10» — дописывает
    диапазон в ссылку как t=95&end=130."""
    if youtube_url_kind(url) != 'video':
        return url
    m = _CELL_RANGE_RE.match(text_after_url or '')
    if not m:
        return url
    start, end = parse_timecode(m.group(1)), parse_timecode(m.group(2))
    if start is None or end is None or end <= start:
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop('start', None)
    qs['t'] = [str(start)]
    qs['end'] = [str(end)]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
