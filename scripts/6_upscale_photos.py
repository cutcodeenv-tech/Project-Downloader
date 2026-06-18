#!/usr/bin/env python3
"""Массовый апскейл фото через Real-ESRGAN.

Исходник переносится в images_cropped/noscale/, а апскейленная версия
сохраняется в images_cropped/ под тем же именем.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from photo_placeholder_ops import (
    build_realesrgan_cmd,
    find_source_image,
    install_realesrgan,
    is_realesrgan_installed,
    replace_source_with_upscaled,
    resolve_upscaled_output,
)
from path_utils import get_base_dir as _get_base_dir, get_data_dir as _get_data_dir


BASE_DIR = _get_base_dir(__file__)
DATA_DIR = _get_data_dir(__file__)


def _load_names() -> list[str]:
    raw = (os.getenv("UPSCALE_NAMES_JSON") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Некорректный UPSCALE_NAMES_JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("UPSCALE_NAMES_JSON должен быть JSON-массивом")
    return [str(item).strip() for item in data if str(item).strip()]


def _run_logged(cmd: list[str], cwd: Path | None = None) -> None:
    print("▶ " + " ".join(str(part) for part in cmd))
    proc = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stdout or "").strip().splitlines()[-30:]
        for line in tail:
            print(line)
        raise RuntimeError(f"Команда завершилась с кодом {proc.returncode}")
    if proc.stdout:
        tail = proc.stdout.strip().splitlines()[-10:]
        for line in tail:
            print(line)


def main() -> int:
    project_name = (os.getenv("PROJECT_NAME") or "").strip()
    upd_subdir = (os.getenv("UPD_SUBDIR") or "").strip()
    names = _load_names()
    scale = int(os.getenv("UPSCALE_SCALE") or "2")

    if not project_name:
        raise RuntimeError("PROJECT_NAME не задан")
    if not names:
        raise RuntimeError("Список файлов для апскейла пуст")
    if scale not in (2, 4):
        raise RuntimeError("Поддерживаются только scale 2x и 4x")

    src_dir = DATA_DIR / project_name / "images_cropped"
    if upd_subdir:
        src_dir = src_dir / upd_subdir

    if not src_dir.exists():
        raise RuntimeError(f"Папка исходников не найдена: {src_dir}")
    noscale_dir = src_dir / "noscale"

    if not is_realesrgan_installed(BASE_DIR):
        print("ℹ Real-ESRGAN не найден локально. Запускаю установку...")
        install_realesrgan(BASE_DIR, sys.executable)

    total = len(names)
    success = 0

    for index, name in enumerate(names, 1):
        print(f"\n[{index}/{total}] {name}")
        source_path = find_source_image(src_dir, name)
        if source_path is None:
            print(f"❌ Исходное изображение не найдено: {name}")
            continue

        with tempfile.TemporaryDirectory(prefix="realesrgan_", dir=str(src_dir)) as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)

            print(f"🔼 Апскейл: {source_path.name} ({scale}x)")
            _run_logged(
                build_realesrgan_cmd(BASE_DIR, source_path, tmp_dir, scale=scale),
                cwd=BASE_DIR / "tools" / "Real-ESRGAN",
            )

            upscaled_path = resolve_upscaled_output(tmp_dir, source_path.name)
            if upscaled_path is None:
                print("❌ Real-ESRGAN не создал выходной файл")
                continue

            final_source = replace_source_with_upscaled(source_path, upscaled_path, backup_dir=noscale_dir)
            print(f"✓ Апскейл сохранён: {final_source.name}")
            print(f"✓ Оригинал перемещён в: {noscale_dir / source_path.name}")

        success += 1

    print(f"\n=== Апскейл завершён: {success}/{total} ===")
    return 0 if success == total else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)
