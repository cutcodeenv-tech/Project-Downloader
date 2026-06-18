#!/usr/bin/env python3
"""
Motion Array Downloader
Скачивает файлы с motionarray.com через cookies аккаунта.
Зависимостей нет — только стандартная библиотека Python.
"""

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlencode, urlparse

BASE_URL = "https://motionarray.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
    "Origin": BASE_URL,
}

COOKIES_FILE = Path(__file__).parent / "cookies.txt"
OUTPUT_DIR = Path(__file__).parent / "downloads"


def build_opener() -> urllib.request.OpenerDirector:
    jar = MozillaCookieJar(str(COOKIES_FILE))
    if not COOKIES_FILE.exists():
        print(f"❌ Файл cookies не найден: {COOKIES_FILE}")
        sys.exit(1)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        print(f"❌ Не удалось загрузить cookies: {e}")
        sys.exit(1)
    print(f"🍪 Cookies загружены ({len(jar)} шт.)")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(HEADERS.items())
    return opener


def get(
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout: int = 15,
    extra_headers: dict | None = None,
) -> tuple[int, bytes, str]:
    """Returns (status, body, final_url). final_url differs from url when redirected."""
    try:
        headers = {"Accept-Encoding": "gzip, deflate"}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=timeout) as r:
            data = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                data = gzip.decompress(data)
            elif enc == "deflate":
                data = zlib.decompress(data)
            return r.status, data, r.url
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except Exception:
        return 0, b"", url


def post(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict,
    timeout: int = 15,
    extra_headers: dict | None = None,
) -> tuple[int, bytes, str]:
    """POST form data. Returns (status, body, final_url)."""
    try:
        headers = {
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(
            url, data=urlencode(data).encode(), headers=headers, method="POST"
        )
        with opener.open(req, timeout=timeout) as r:
            body = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            return r.status, body, r.url
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except Exception:
        return 0, b"", url


DOWNLOAD_ENDPOINT = f"{BASE_URL}/proxy/download/v1/download/direct"

# Slug из URL → assetTypeId для download API
SLUG_TO_ASSET_TYPE: dict[str, str] = {
    "stock-motion-graphics": "motionGraphics",
    "after-effects-templates": "afterEffectsTemplate",
    "premiere-pro-templates": "premiereProTemplate",
    "motion-graphics-templates": "mogrt",
    "stock-video": "footage",
    "royalty-free-music": "music",
    "sound-effects": "soundEffect",
    "stock-photos": "stockPhoto",
    "graphics": "graphic",
    "luts": "lut",
    "davinci-resolve-templates": "davinciResolveTemplate",
    "davinci-resolve-macros": "davinciResolveMacro",
    "final-cut-pro-templates": "finalCutProTemplate",
    "after-effects-presets": "afterEffectsPreset",
    "premiere-pro-presets": "premiereProPreset",
    "premiere-rush-templates": "premiereRushTemplate",
    "voice-over": "voiceOver",
}

# assetTypeId → формат файла по умолчанию
ASSET_TYPE_FORMAT: dict[str, str] = {
    "footage": "mov",
    "music": "mp3",
    "soundEffect": "mp3",
    "stockPhoto": "jpg",
    "voiceOver": "mp3",
}


def _asset_type_from_url(url: str) -> str:
    for slug, asset_type in SLUG_TO_ASSET_TYPE.items():
        if slug in url:
            return asset_type
    return "motionGraphics"


def post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict,
    timeout: int = 15,
    extra_headers: dict | None = None,
) -> tuple[int, bytes, str]:
    """POST JSON body. Returns (status, body, final_url)."""
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "X-Requested-With": "XMLHttpRequest",
        }
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with opener.open(req, timeout=timeout) as r:
            resp = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                resp = gzip.decompress(resp)
            elif enc == "deflate":
                resp = zlib.decompress(resp)
            return r.status, resp, r.url
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except Exception:
        return 0, b"", url


def _proxy_get_files(
    opener: urllib.request.OpenerDirector,
    product_id: str,
    asset_type: str = "",
    referer: str = "",
) -> list[dict]:
    """Try proxy API endpoints to get a file list with fileIds."""
    ajax = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    if referer:
        ajax["Referer"] = referer

    candidates = [
        f"{BASE_URL}/proxy/download/v1/assets/{product_id}/files",
        f"{BASE_URL}/proxy/download/v1/assets/{product_id}",
        f"{BASE_URL}/proxy/download/v1/products/{product_id}/files",
        f"{BASE_URL}/proxy/download/v1/products/{product_id}",
        f"{BASE_URL}/proxy/download/v1/download/options?assetId={product_id}&assetTypeId={asset_type}&applicationTypeId=motion_array",
        f"{BASE_URL}/proxy/catalog/v1/assets/{product_id}",
        f"{BASE_URL}/proxy/catalog/v1/assets/{product_id}/files",
    ]
    for ep in candidates:
        status, body, _ = get(opener, ep, extra_headers=ajax)
        print(f"   {ep.replace(BASE_URL,'')}  →  {status}")
        if status != 200 or not body:
            continue
        try:
            data = json.loads(body)
        except Exception:
            snippet = body[:150].decode("utf-8", errors="replace")
            print(f"   (не JSON: {snippet})")
            continue
        files = _extract_file_list(data)
        if files:
            return files
        # Если JSON нашёлся но fileId не нашли — покажем ключи для диагностики
        top_keys = list(data.keys())[:10] if isinstance(data, dict) else type(data).__name__
        print(f"   (JSON без PRD-id, ключи: {top_keys})")
    return []


# Приоритет суффиксов fileId: чем меньше индекс — тем предпочтительнее
_QUALITY_ORDER = ["source", "original", "4k", "hd", "high", "standard", "low", "preview"]


def _quality_rank(file_id: str) -> int:
    suffix = file_id.rsplit("-", 1)[-1].lower()
    try:
        return _QUALITY_ORDER.index(suffix)
    except ValueError:
        return len(_QUALITY_ORDER)


def _extract_file_list(data: object) -> list[dict]:
    """Recursively find file entries (PRD-... IDs), returns only best quality per product."""
    results = []
    if isinstance(data, dict):
        fid = data.get("id") or data.get("fileId") or data.get("file_id") or ""
        if isinstance(fid, str) and re.match(r"PRD-\d+-.+", fid):
            results.append({
                "id": fid,
                "format": data.get("assetFormatId") or data.get("format") or "zip",
                "fileName": (
                    data.get("fileName") or data.get("file_name")
                    or data.get("name") or fid + ".zip"
                ),
            })
        for v in data.values():
            results.extend(_extract_file_list(v))
    elif isinstance(data, list):
        for item in data:
            results.extend(_extract_file_list(item))
    return results


def _best_files(files: list[dict]) -> list[dict]:
    """Keep only the highest-quality file per product (skip preview if source exists)."""
    if not files:
        return files
    # Sort by quality rank ascending (source=0, preview=last)
    files = sorted(files, key=lambda f: _quality_rank(f["id"]))
    # Drop explicit previews if better quality exists
    top_rank = _quality_rank(files[0]["id"])
    if top_rank < _QUALITY_ORDER.index("preview"):
        files = [f for f in files if _quality_rank(f["id"]) < _QUALITY_ORDER.index("preview")]
    return files


def _files_from_nuxt(page_text: str, product_id: str) -> list[dict]:
    """Extract file entries from window.__NUXT__ or __INITIAL_STATE__ page data."""
    results = []
    for var in ("window.__NUXT__", "window.__INITIAL_STATE__"):
        idx = page_text.find(var)
        if idx == -1:
            continue
        brace = page_text.find("{", idx)
        if brace == -1:
            continue
        depth = 0
        for i, ch in enumerate(page_text[brace:], brace):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = page_text[brace : i + 1]
                    raw = re.sub(r":undefined\b", ":null", raw)
                    raw = re.sub(r":NaN\b", ":null", raw)
                    try:
                        data = json.loads(raw)
                        results.extend(_extract_file_list(data))
                    except Exception:
                        # Fallback: regex for PRD-id-... patterns
                        for m in re.finditer(
                            rf'"(PRD-{product_id}-[A-Za-z0-9_-]+-[a-z]+)"', raw
                        ):
                            results.append({
                                "id": m.group(1),
                                "format": "zip",
                                "fileName": f"{product_id}_{m.group(1).split('-')[-1]}.zip",
                            })
                    break
        if results:
            break
    return results



def sizeof_fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip(". ")[:180]


def extract_id(url: str) -> str | None:
    m = re.search(r"-(\d+)(?:/|\?|$)", url)
    return m.group(1) if m else None


def _find_in_json(obj, keys: tuple) -> str | None:
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and isinstance(obj[k], str) and obj[k].startswith("http"):
                return obj[k]
        for v in obj.values():
            result = _find_in_json(v, keys)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_in_json(item, keys)
            if result:
                return result
    return None


def _extract_files_from_json(obj, product_name: str) -> list[dict]:
    links = []
    if isinstance(obj, dict):
        file_url = (
            obj.get("url") or obj.get("download_url") or obj.get("downloadUrl")
            or obj.get("link") or obj.get("src")
        )
        if file_url and isinstance(file_url, str) and file_url.startswith("http"):
            ext = Path(urlparse(file_url).path).suffix.lower()
            if ext in {".zip", ".rar", ".aep", ".mogrt", ".mp4", ".mov", ".prproj", ""}:
                links.append({
                    "name": obj.get("name") or obj.get("label") or obj.get("resolution") or obj.get("quality") or "file",
                    "url": file_url,
                    "product_name": product_name,
                })
        for v in obj.values():
            links.extend(_extract_files_from_json(v, product_name))
    elif isinstance(obj, list):
        for item in obj:
            links.extend(_extract_files_from_json(item, product_name))
    return links


AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}


def get_links(opener: urllib.request.OpenerDirector, url: str) -> list[dict]:
    product_id = extract_id(url)
    if not product_id:
        print("❌ Не удалось определить ID продукта из URL.")
        return []

    asset_type = _asset_type_from_url(url)
    product_name = f"product_{product_id}"

    # 1. Получаем список файлов (с fileId) через proxy API
    print(f"   Ищем файлы для id={product_id} (type={asset_type})...")
    files = _proxy_get_files(opener, product_id, asset_type=asset_type, referer=url)

    # 2. Если proxy не дал — пробуем Nuxt/InitialState из страницы продукта
    csrf_token = None
    if not files:
        print(f"   Загружаем страницу для извлечения fileId...")
        status, body, _ = get(opener, url, timeout=20)
        if status in (401, 403):
            print(f"❌ Ошибка {status} — проверьте cookies / подписку.")
            return []
        page_text = body.decode("utf-8", errors="ignore") if body else ""
        if page_text:
            files = _files_from_nuxt(page_text, product_id)
            # CSRF токен из <meta name="_token"> или <meta name="csrf-token">
            m = re.search(r'<meta[^>]+name=["\'](?:_token|csrf-token)["\'][^>]+content=["\']([^"\']+)', page_text)
            if m:
                csrf_token = m.group(1)
            # Название продукта из <title>
            m = re.search(r"<title>([^<]+)</title>", page_text, re.I)
            if m:
                title = m.group(1).split("|")[0].strip()
                if title and title.lower() != "motion array":
                    product_name = title

    # 2b. Fallback: старая страница /browse/download/{id} (другая Nuxt-структура)
    if not files:
        print(f"   Пробуем /browse/download/{product_id}...")
        browse_url = f"{BASE_URL}/browse/download/{product_id}"
        _, bd, _ = get(opener, browse_url, timeout=15)
        if bd:
            browse_text = bd.decode("utf-8", errors="ignore")
            files = _files_from_nuxt(browse_text, product_id)
            if not csrf_token:
                m = re.search(r'<meta[^>]+name=["\'](?:_token|csrf-token)["\'][^>]+content=["\']([^"\']+)', browse_text)
                if m:
                    csrf_token = m.group(1)

    if not files:
        print("   ⚠️  Не удалось получить список файлов продукта.")
        return []

    files = _best_files(files)
    default_fmt = ASSET_TYPE_FORMAT.get(asset_type, "zip")
    print(f"   Файлов к загрузке: {len(files)} ({', '.join(f['id'].rsplit('-',1)[-1] for f in files)})")
    for f in files:
        print(f"   fileId: {f['id']}")

    # Доп. заголовки для download/direct — Referer на страницу продукта обязателен
    dl_headers = {
        "Referer": url,
        "Origin": BASE_URL,
    }
    if csrf_token:
        dl_headers["X-CSRF-TOKEN"] = csrf_token

    # 3. Для каждого файла — POST /proxy/download/v1/download/direct → signed URL
    links = []
    for f in files:
        payload = {
            "applicationTypeId": "motion_array",
            "assetId": product_id,
            "assetTypeId": asset_type,
            "assetFormatId": f.get("format", default_fmt),
            "fileId": f["id"],
            "fileName": f.get("fileName", f"{product_id}.zip"),
        }
        print(f"   ⬇️  {f.get('fileName', f['id'])}...")
        st, bd, _ = post_json(opener, DOWNLOAD_ENDPOINT, payload, extra_headers=dl_headers)
        if st in (401, 403):
            err_body = bd.decode("utf-8", errors="ignore")[:300] if bd else ""
            print(f"❌ Ошибка {st} — нет доступа. Ответ: {err_body}")
            break
        if st != 200 or not bd:
            print(f"   ⚠️  download/direct вернул {st}")
            continue
        try:
            resp = json.loads(bd)
        except Exception:
            print(f"   ⚠️  Не JSON: {bd[:200]}")
            continue

        if not resp.get("isAllowed"):
            print(f"   ⚠️  isAllowed=false: {resp}")
            continue

        for dl_url in resp.get("downloadUrls", []):
            links.append({
                "name": f.get("fileName", f["id"]),
                "url": dl_url,
                "product_name": product_name,
            })

    return links


def download_file(opener: urllib.request.OpenerDirector, url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with opener.open(req, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            downloaded = 0
            start = time.time()
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        speed = downloaded / max(time.time() - start, 0.1)
                        print(f"\r  {pct:.1f}%  {sizeof_fmt(downloaded)}/{sizeof_fmt(total)}  {sizeof_fmt(speed)}/s   ", end="", flush=True)
        print(f"\r  ✅ {dest.name} ({sizeof_fmt(downloaded)})                          ")
        return True
    except Exception as e:
        print(f"\r  ❌ Ошибка: {e}")
        if dest.exists():
            dest.unlink()
        return False


def process(opener: urllib.request.OpenerDirector, url: str):
    print("🔍 Получаем ссылки...")
    links = get_links(opener, url)

    if not links:
        print("❌ Ссылки для скачивания не найдены.")
        return

    product_dir = OUTPUT_DIR / sanitize(links[0]["product_name"])
    product_dir.mkdir(parents=True, exist_ok=True)

    print(f"📦 {links[0]['product_name']}")
    print(f"📎 Файлов: {len(links)}")

    for lnk in links:
        parsed = urlparse(lnk["url"])
        filename = Path(parsed.path).name or sanitize(lnk["name"]) + ".bin"
        dest = product_dir / filename

        if dest.exists():
            print(f"  ⏭️  Уже есть: {filename}")
            continue

        print(f"  ⬇️  {lnk['name']}")
        download_file(opener, lnk["url"], dest)
        time.sleep(0.5)

    print(f"📂 Сохранено в: {product_dir.resolve()}")


def main():
    print("=" * 50)
    print("  Motion Array Downloader")
    print("=" * 50)

    opener = build_opener()

    try:
        status, body, _ = get(opener, f"{BASE_URL}/api/auth/me")
        if status == 200:
            user = json.loads(body)
            name = user.get("name") or user.get("email") or "—"
            print(f"👤 Аккаунт: {name}")
    except Exception:
        pass

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📂 Папка загрузок: {OUTPUT_DIR.resolve()}")
    print()

    while True:
        try:
            url = input("🔗 Ссылка (или 'q' для выхода): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Выход.")
            break

        if url.lower() in ("q", "quit", "exit", "выход"):
            print("👋 Выход.")
            break

        if not url.startswith("http"):
            print("❌ Некорректная ссылка.\n")
            continue

        process(opener, url)
        print()


if __name__ == "__main__":
    main()
