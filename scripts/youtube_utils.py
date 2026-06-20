#!/usr/bin/env python3
"""Единый классификатор YouTube-ссылок для пайплайна скачивания.

Правила (общие для генерации списка, скачивания и переименования):
- канал (/@handle, /channel/.., /c/.., /user/..) — пропускаем;
- shorts — пропускаем;
- плейлист без конкретного видео — пропускаем;
- watch?v=ID&list=.. — берём только видео ID (list= отбрасывается);
- скачиваем только то, что youtube_url_kind() считает 'video'.
"""

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
