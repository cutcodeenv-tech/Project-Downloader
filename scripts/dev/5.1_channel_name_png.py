#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create PNG overlays with transparent background from Google Sheets columns A and E.

Text format is defined by TEXT_TEMPLATE.
Defaults: 621x50 px minimum, Montserrat Bold, output to Desktop folder.

Requires: gspread, google-auth, python-dotenv, Pillow.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # noqa: BLE001
    raise SystemExit(
        "Missing Pillow. Install it with: python -m pip install pillow"
    ) from exc


IMAGE_WIDTH = 621
IMAGE_HEIGHT = 50
PADDING_X = 8
PADDING_Y = 6
FONT_SIZE = 36
TEXT_COLOR = (255, 255, 255, 255)
SHADOW_COLOR = (0, 0, 0, 140)
SHADOW_OFFSETS = [(1, 1)]

TEXT_TEMPLATE = (
    "\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a: "
    "Youtube-\u043a\u0430\u043d\u0430\u043b \u00ab{channel}\u00bb"
)
FOLDER_PREFIX = "\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438"

HEADER_NAME_TOKENS = {
    "name",
    "title",
    "video",
    "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435",
    "\u0438\u043c\u044f",
    "\u0444\u0430\u0439\u043b",
}
HEADER_CHANNEL_TOKENS = {"channel", "source", "\u043a\u0430\u043d\u0430\u043b", "\u0438\u0441\u0442\u043e\u0447"}


def die(message: str, code: int = 1) -> None:
    print(f"[ERR] {message}", file=sys.stderr)
    sys.exit(code)


def input_nonempty(prompt: str, default: Optional[str] = None) -> str:
    while True:
        answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        print("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 "
              "\u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0432\u0432\u043e\u0434.")


def parse_spreadsheet_id(value: str) -> str:
    value = value.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", value):
        return value
    die("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0438\u0437\u0432\u043b\u0435\u0447\u044c Spreadsheet ID.")
    return ""


def creds_from_env_or_prompt() -> Credentials:
    load_dotenv(override=True)

    info = {
        "type": os.getenv("TYPE"),
        "project_id": os.getenv("PROJECT_ID"),
        "private_key_id": os.getenv("PRIVATE_KEY_ID"),
        "private_key": (os.getenv("PRIVATE_KEY") or "").replace("\\n", "\n"),
        "client_email": os.getenv("CLIENT_EMAIL"),
        "client_id": os.getenv("CLIENT_ID"),
        "auth_uri": os.getenv("AUTH_URI"),
        "token_uri": os.getenv("TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL"),
        "universe_domain": os.getenv("UNIVERSE_DOMAIN"),
    }
    if info["type"] and info["client_email"] and info["private_key"]:
        try:
            return Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Failed to build creds from env: {exc}")

    encoded = (os.getenv("GOOGLE_CREDENTIALS_JSON_B64") or "").strip()
    if encoded:
        try:
            data = base64.b64decode(encoded)
            parsed = json.loads(data.decode("utf-8"))
            return Credentials.from_service_account_info(
                parsed,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] GOOGLE_CREDENTIALS_JSON_B64 invalid: {exc}")

    key_path_env = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if key_path_env:
        path = Path(key_path_env).expanduser().resolve()
        if path.is_file():
            try:
                return Credentials.from_service_account_file(
                    str(path),
                    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] GOOGLE_APPLICATION_CREDENTIALS error: {exc}")
        else:
            print(f"[WARN] GOOGLE_APPLICATION_CREDENTIALS file not found: {path}")

    while True:
        user_path = input(
            "\u041f\u0443\u0442\u044c \u043a JSON \u043a\u043b\u044e\u0447\u0443 \u0441\u0435\u0440\u0432\u0438\u0441\u043d\u043e\u0433\u043e "
            "\u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 (Enter \u2014 \u043e\u0442\u043c\u0435\u043d\u0430): "
        ).strip()
        if not user_path:
            die("\u041d\u0435 \u0437\u0430\u0434\u0430\u043d\u044b \u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u043b\u044f Google API.")
        path = Path(user_path).expanduser().resolve()
        if not path.is_file():
            print("\u0424\u0430\u0439\u043b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0441\u043d\u043e\u0432\u0430.")
            continue
        try:
            return Credentials.from_service_account_file(
                str(path),
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Failed to read JSON: {exc}")


def clean_channel_name(value: str) -> str:
    name = value.strip()
    if len(name) >= 2:
        pairs = [("\u00ab", "\u00bb"), ('"', '"'), ("\u201c", "\u201d"), ("'", "'")]
        for left, right in pairs:
            if name.startswith(left) and name.endswith(right):
                name = name[1:-1].strip()
                break
    return name


def extract_entries(values: Iterable[List[str]]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for idx, row in enumerate(values, start=1):
        name = row[0].strip() if len(row) > 0 else ""
        channel = row[4].strip() if len(row) > 4 else ""
        if not name or not channel:
            continue
        if idx == 1:
            name_lower = name.lower()
            channel_lower = channel.lower()
            if any(token in name_lower for token in HEADER_NAME_TOKENS) or any(
                token in channel_lower for token in HEADER_CHANNEL_TOKENS
            ):
                continue
        cleaned = clean_channel_name(channel)
        if cleaned:
            entries.append((name, cleaned))
    return entries


def default_output_dir() -> Path:
    date_stamp = datetime.now().strftime("%y%m%d")
    folder_name = f"{FOLDER_PREFIX} {date_stamp}"
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    return base / folder_name


def sanitize_filename(name: str, max_len: int = 120) -> str:
    value = name.strip()
    if not value:
        return ""
    value = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", value)
    if len(value) > max_len:
        value = value[:max_len]
    return value


def ensure_unique_path(folder: Path, base_name: str, suffix: str = ".png") -> Path:
    candidate = folder / f"{base_name}{suffix}"
    if not candidate.exists():
        return candidate
    for i in range(2, 1000):
        numbered = folder / f"{base_name}_{i}{suffix}"
        if not numbered.exists():
            return numbered
    die("Too many duplicate filenames.")
    return candidate


def filename_from_column_a(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    path = Path(raw)
    base = path.stem if path.suffix else raw
    return sanitize_filename(base)


def find_montserrat_bold() -> Optional[Path]:
    candidates = [
        "Montserrat-Bold.ttf",
        "Montserrat Bold.ttf",
        "Montserrat-Bold.otf",
    ]
    search_paths = [
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
    ]
    for root in search_paths:
        for name in candidates:
            path = root / name
            if path.is_file():
                return path
    return None


def prompt_for_font_path() -> Path:
    while True:
        user_path = input(
            "\u041f\u0443\u0442\u044c \u043a \u0448\u0440\u0438\u0444\u0442\u0443 Montserrat Bold (.ttf/.otf): "
        ).strip()
        if not user_path:
            print("\u041f\u0443\u0442\u044c \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c.")
            continue
        path = Path(user_path).expanduser().resolve()
        if not path.is_file():
            print("\u0424\u0430\u0439\u043b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0441\u043d\u043e\u0432\u0430.")
            continue
        return path


def measure_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> Tuple[int, int, Tuple[int, int, int, int]]:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height, bbox


def render_text_image(text: str, font_path: Path) -> Image.Image:
    font = ImageFont.truetype(str(font_path), size=FONT_SIZE)
    scratch = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    scratch_draw = ImageDraw.Draw(scratch)
    text_w, text_h, bbox = measure_text(scratch_draw, text, font)

    image_width = max(IMAGE_WIDTH, text_w + 2 * PADDING_X)
    image = Image.new("RGBA", (image_width, IMAGE_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Right-align within the canvas so placement is consistent across different text lengths.
    x = image_width - PADDING_X - text_w - bbox[0]
    y = (IMAGE_HEIGHT - text_h) / 2 - bbox[1]

    for dx, dy in SHADOW_OFFSETS:
        draw.text((x + dx, y + dy), text, font=font, fill=SHADOW_COLOR)
    draw.text((x, y), text, font=font, fill=TEXT_COLOR)
    return image


def load_rows(spreadsheet_id: str, worksheet_name: str, gc: gspread.Client) -> List[List[str]]:
    worksheet = gc.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    return worksheet.get_all_values()


def main() -> None:
    print("=== Channel PNG generator ===")
    sheet_input = input_nonempty("\u0421\u0441\u044b\u043b\u043a\u0430 \u0438\u043b\u0438 ID \u0442\u0430\u0431\u043b\u0438\u0446\u044b")
    spreadsheet_id = parse_spreadsheet_id(sheet_input)
    worksheet_name = input_nonempty("\u0418\u043c\u044f \u043b\u0438\u0441\u0442\u0430", "1_PullTube")

    creds = creds_from_env_or_prompt()
    gc = gspread.authorize(creds)

    try:
        values = load_rows(spreadsheet_id, worksheet_name, gc)
    except Exception as exc:  # noqa: BLE001
        die(f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c \u043b\u0438\u0441\u0442: {exc}")

    entries = extract_entries(values)
    if not entries:
        die("\u041d\u0435\u0442 \u0441\u0442\u0440\u043e\u043a \u0441 \u0434\u0430\u043d\u043d\u044b\u043c\u0438 \u0432 \u043a\u043e\u043b\u043e\u043d\u043a\u0430\u0445 A \u0438 E.")

    font_path = find_montserrat_bold()
    if not font_path:
        print("Montserrat Bold not found in standard font folders.")
        font_path = prompt_for_font_path()

    default_dir = default_output_dir()
    out_dir_input = input(
        f"\u041f\u0430\u043f\u043a\u0430 \u0434\u043b\u044f PNG (Enter = {default_dir}): "
    ).strip()
    out_dir = Path(out_dir_input).expanduser().resolve() if out_dir_input else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for idx, (raw_name, channel) in enumerate(entries, start=1):
        text = TEXT_TEMPLATE.format(channel=channel)
        image = render_text_image(text, font_path)

        base_name = filename_from_column_a(raw_name)
        if not base_name:
            base_name = f"channel_{idx:03d}"
        output_path = ensure_unique_path(out_dir, base_name)
        image.save(output_path, format="PNG")
        written += 1

    print(f"Saved {written} PNG files to: {out_dir}")


if __name__ == "__main__":
    main()
