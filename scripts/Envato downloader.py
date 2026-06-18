#!/usr/bin/env python3
"""
Envato Elements Downloader
Скачивает файлы с app.envato.com через cookies аккаунта.
Зависимостей нет — только стандартная библиотека Python.

Рабочий алгоритм:
  1. Загрузить HTML страницы + .data (без _routes) → собрать все UUID
  2. Перебрать UUID через GET /download.data → получить download URL
  3. Выбрать лучшее качество (source > hd > ...), скачать
"""

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse, urlencode, unquote

BASE_URL     = "https://app.envato.com"
COOKIES_FILE = Path(__file__).parent / "cookies.txt"
OUTPUT_DIR   = Path(__file__).parent / "downloads"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Приоритет качества (меньший индекс = лучше)
QUALITY_ORDER = ["source", "original", "4k", "uhd", "hd", "high",
                 "medium", "standard", "low", "preview"]

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)


# ──────────────────────────────────────────────────────────────────────────────
# HTTP
# ──────────────────────────────────────────────────────────────────────────────

def build_opener() -> urllib.request.OpenerDirector:
    jar = MozillaCookieJar(str(COOKIES_FILE))
    if not COOKIES_FILE.exists():
        print(f"❌  Файл cookies не найден: {COOKIES_FILE}")
        sys.exit(1)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        print(f"❌  Не удалось загрузить cookies: {e}")
        sys.exit(1)
    print(f"🍪  Cookies загружены ({len(jar)} шт.)")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def _decompress(data: bytes, enc: str) -> bytes:
    try:
        if enc == "gzip":    return gzip.decompress(data)
        if enc == "deflate": return zlib.decompress(data)
    except Exception:
        pass
    return data


def get(opener, url: str, extra: dict | None = None,
        timeout: int = 30) -> tuple[int, bytes]:
    h = {
        "Accept-Encoding": "gzip, deflate",   # br убран — нет brotli в stdlib
        "Accept":          "*/*",
        "Referer":         BASE_URL,
    }
    if extra:
        h.update(extra)
    try:
        req = urllib.request.Request(url, headers=h)
        with opener.open(req, timeout=timeout) as r:
            body = _decompress(r.read(), r.headers.get("Content-Encoding", ""))
            return r.status, body
    except urllib.error.HTTPError as e:
        try:   body = _decompress(e.read(), e.headers.get("Content-Encoding", ""))
        except Exception: body = b""
        return e.code, body
    except Exception:
        return 0, b""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def parse_item_url(url: str) -> tuple[str | None, str]:
    """Возвращает (item_uuid, item_type) из URL вида /stock-video/{uuid}."""
    parts = urlparse(url).path.strip("/").split("/")
    item_uuid = None
    item_type = "stock-video"
    for part in parts:
        if UUID_RE.fullmatch(part):
            item_uuid = part
        elif part:
            item_type = part
    if not item_uuid:
        m = UUID_RE.search(url)
        item_uuid = m.group(0) if m else None
    return item_uuid, item_type


def url_quality_rank(dl_url: str) -> int:
    """Ранжирует качество по имени файла в download URL."""
    path = urlparse(dl_url).path.lower()
    if "preview" in path:
        return 999
    for i, name in enumerate(QUALITY_ORDER):
        if name in path:
            return i
    return len(QUALITY_ORDER)


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip(". ")[:180]


def filename_from_url(dl_url: str, fallback: str) -> str:
    """
    Извлекает имя файла из параметра response-content-disposition в download URL.
    Пример: ...?response-content-disposition=attachment%3B+filename%2A%3DUTF-8%27%27woman-exploring...mov
    """
    parsed = urlparse(dl_url)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    # Основной источник: response-content-disposition
    cd_values = qs.get("response-content-disposition", [])
    if cd_values:
        cd = unquote(cd_values[0])   # декодируем %3B → ; и т.д.
        # filename*=UTF-8''имя.ext  (RFC 5987)
        m = re.search(r"filename\*\s*=\s*UTF-8''([^;\s]+)", cd, re.I)
        if m:
            return sanitize(unquote(m.group(1)))
        # filename="имя.ext"  или  filename=имя.ext
        m = re.search(r'filename\s*=\s*"?([^";\r\n]+)"?', cd, re.I)
        if m:
            return sanitize(m.group(1).strip())

    # Fallback: имя файла из пути URL (source.mov / hd.mov и т.п.)
    name = Path(parsed.path).name
    return sanitize(name) if name and "." in name else fallback


def sizeof_fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def parse_download_url(body: bytes) -> str | None:
    """Извлекает downloadUrl из Remix RSF ответа [..., 'downloadUrl', 'https://...']."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception:
        return None
    if isinstance(data, list):
        for i, item in enumerate(data):
            if item == "downloadUrl" and i + 1 < len(data):
                val = data[i + 1]
                if isinstance(val, str) and val.startswith("https://"):
                    return val
    if isinstance(data, dict):
        for key in ("downloadUrl", "download_url", "url"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("https://"):
                return val
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Core: collect UUIDs → probe → pick best quality
# ──────────────────────────────────────────────────────────────────────────────

def collect_uuids(opener, item_uuid: str, item_type: str) -> list[str]:
    """
    Загружает HTML страницы и .data (без _routes).
    Возвращает список уникальных UUID-кандидатов (без самого item_uuid).
    """
    referer = f"{BASE_URL}/{item_type}/{item_uuid}"
    extra   = {"Referer": referer, "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin", "sec-fetch-dest": "empty"}
    combined = ""

    # 1. HTML страницы
    st, body = get(opener, referer, timeout=30)
    print(f"   HTML страницы  → {st},  {len(body):,} байт")
    if st == 200 and body:
        combined += body.decode("utf-8", errors="ignore")

    # 2. .data без _routes (полный набор данных роутов)
    st, body = get(opener, f"{referer}.data", extra=extra)
    print(f"   .data          → {st},  {len(body):,} байт")
    if st == 200 and body:
        combined += body.decode("utf-8", errors="ignore")

    all_uuids = list(dict.fromkeys(UUID_RE.findall(combined)))
    return [u for u in all_uuids if u.lower() != item_uuid.lower()]


def _download_data(opener, item_uuid: str, item_type: str,
                   asset_uuid: str | None = None) -> str | None:
    """
    GET /download.data с нужными параметрами.
    asset_uuid=None → запрос без assetUuid (работает для music и др. типов).
    Возвращает downloadUrl или None.
    """
    params: dict = {
        "itemUuid": item_uuid,
        "itemType": item_type,
        "_routes":  "routes/download/route",
    }
    if asset_uuid:
        params["assetUuid"] = asset_uuid

    extra = {
        "Referer":        f"{BASE_URL}/{item_type}/{item_uuid}",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    st, body = get(opener, f"{BASE_URL}/download.data?{urlencode(params)}", extra=extra)
    if st == 200:
        return parse_download_url(body)
    return None


def find_best_download(opener, item_uuid: str, item_type: str,
                       candidates: list[str]) -> str | None:
    """
    1. Сначала пробует прямой вызов без assetUuid (music, sound-effects и др.)
    2. Если не сработало — перебирает UUID-кандидаты (stock-video и др.)
    Возвращает download URL с лучшим качеством.
    """
    # ── Шаг 1: прямой вызов без assetUuid ────────────────────────────────────
    print("   Пробуем прямой вызов (без assetUuid)...")
    dl_url = _download_data(opener, item_uuid, item_type)
    if dl_url:
        fname = Path(urlparse(dl_url).path).name
        print(f"   ✅  {fname}")
        return dl_url

    # ── Шаг 2: перебор UUID-кандидатов ───────────────────────────────────────
    print(f"   Перебираем assetUuid... ({len(candidates)} кандидатов)")
    hits: list[tuple[int, str]] = []

    for uid in candidates:
        dl_url = _download_data(opener, item_uuid, item_type, asset_uuid=uid)
        if dl_url:
            rank  = url_quality_rank(dl_url)
            fname = Path(urlparse(dl_url).path).name
            print(f"   ✅  {uid[:8]}…  →  {fname}  (rank={rank})")
            hits.append((rank, dl_url))
            if rank == 0:   # source — лучше не будет
                break

    if not hits:
        return None

    hits.sort(key=lambda x: x[0])
    best_url = hits[0][1]
    print(f"   🏆  Лучшее: {Path(urlparse(best_url).path).name}")
    return best_url


# ──────────────────────────────────────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────────────────────────────────────

def download_file(opener, url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with opener.open(req, timeout=300) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done  = 0
            start = time.time()
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct   = done / total * 100
                        speed = done / max(time.time() - start, 0.1)
                        print(f"\r  {pct:.1f}%  {sizeof_fmt(done)}/{sizeof_fmt(total)}"
                              f"  {sizeof_fmt(speed)}/s   ", end="", flush=True)
        print(f"\r  ✅  {dest.name} ({sizeof_fmt(done)})                          ")
        return True
    except Exception as e:
        print(f"\r  ❌  Ошибка: {e}")
        dest.unlink(missing_ok=True)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Main flow
# ──────────────────────────────────────────────────────────────────────────────

def process(opener, item_url: str):
    item_uuid, item_type = parse_item_url(item_url)
    if not item_uuid:
        print("❌  Не удалось извлечь UUID из ссылки.")
        return

    print(f"   item_uuid={item_uuid}")
    print(f"   item_type={item_type}\n")

    # Шаг 1: собрать UUID-кандидаты
    print("📋  Собираем UUID-кандидаты...")
    candidates = collect_uuids(opener, item_uuid, item_type)
    if not candidates:
        print("❌  UUID не найдены на странице.")
        return

    # Шаг 2: перебрать через /download.data, выбрать лучшее
    print(f"\n🔍  Подбираем лучшее качество...")
    dl_url = find_best_download(opener, item_uuid, item_type, candidates)

    if not dl_url:
        print("❌  Не удалось получить download URL.")
        return

    # Шаг 3: скачать
    fname       = filename_from_url(dl_url, fallback=f"{item_type}_{item_uuid[:8]}.bin")
    product_dir = OUTPUT_DIR / sanitize(f"{item_type}_{item_uuid[:8]}")
    product_dir.mkdir(parents=True, exist_ok=True)
    dest        = product_dir / fname

    if dest.exists():
        print(f"\n  ⏭️   Уже скачан: {fname}")
        return

    print(f"\n  ⬇️   {fname}")
    download_file(opener, dl_url, dest)
    print(f"📂  Сохранено в: {product_dir.resolve()}")


def main():
    print("=" * 55)
    print("  Envato Elements Downloader")
    print("=" * 55)

    opener = build_opener()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📂  Папка загрузок: {OUTPUT_DIR.resolve()}\n")

    print("💡  Можно вставить несколько ссылок сразу (каждая на новой строке).")
    print("    Пустая строка — начать скачивание. 'q' — выход.\n")

    while True:
        # Собираем ссылки до пустой строки
        urls: list[str] = []
        try:
            while True:
                line = input("🔗  " if not urls else "   ").strip()
                if line.lower() in ("q", "quit", "exit", "выход"):
                    print("👋  Выход.")
                    return
                if not line:
                    break
                # Одна строка может содержать несколько ссылок через пробел
                for part in line.split():
                    if part.startswith("http"):
                        urls.append(part)
                    else:
                        print(f"   ⚠️  Пропускаем (не ссылка): {part}")
        except (KeyboardInterrupt, EOFError):
            print("\n👋  Выход.")
            break

        if not urls:
            continue

        print(f"\n📥  Ссылок к скачиванию: {len(urls)}\n")
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            process(opener, url)
            print()


if __name__ == "__main__":
    main()
