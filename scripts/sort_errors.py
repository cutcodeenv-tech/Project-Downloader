#!/usr/bin/env python3
"""
Сводка ошибок проекта: читает все error-файлы в database/,
группирует по B-блокам, выводит summary в терминал,
сохраняет итог в database/errors_summary_<дата>.txt
"""

import os
import csv
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from path_utils import get_data_dir

_DATA_DIR = get_data_dir(__file__)

LABELS = {
    'image':       'Изображения не скачаны',
    'screenshot':  'Скриншоты не созданы',
    'motionarray': 'MotionArray не переименованы',
}


def get_project_name():
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Название не может быть пустым.')


def _group_key(source: str) -> str:
    """B3_1 → B3, upd_2024-01-01 → upd, иное → '?'"""
    if source.startswith('upd_'):
        return 'upd'
    m = re.match(r'^([A-Za-z]+\d+)', source)
    return m.group(1) if m else '?'


def collect_errors(project_name: str) -> list:
    db_dir = _DATA_DIR / project_name / "database"
    errors = []

    # 1. Ошибки скачивания изображений
    img_csv = db_dir / f"os_doc_{project_name}_download_img_errors.csv"
    if img_csv.exists():
        try:
            with img_csv.open('r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    src = (row.get('source_address') or '').strip()
                    url = (row.get('url') or '').strip()
                    if src or url:
                        errors.append({'type': 'image', 'source': src, 'url': url})
        except Exception as e:
            print(f"⚠️  {img_csv.name}: {e}")

    # 2. Ошибки скриншотов (manual_screenshots.txt — source_address<TAB>url)
    manual_txt = db_dir / "manual_screenshots.txt"
    if manual_txt.exists():
        try:
            with manual_txt.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t', 1)
                    src = parts[0].strip()
                    url = parts[1].strip() if len(parts) > 1 else ''
                    if src:
                        errors.append({'type': 'screenshot', 'source': src, 'url': url})
        except Exception as e:
            print(f"⚠️  {manual_txt.name}: {e}")

    # 3. MotionArray — только строки со статусом FAILED
    ma_log = db_dir / f"osnovateli_doc_{project_name}_motionarray_rename_log.csv"
    if ma_log.exists():
        try:
            with ma_log.open('r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if 'FAILED' in (row.get('status') or ''):
                        src = (row.get('source_address') or '').strip()
                        url = (row.get('motionarray_url') or '').strip()
                        errors.append({'type': 'motionarray', 'source': src, 'url': url})
        except Exception as e:
            print(f"⚠️  {ma_log.name}: {e}")

    return errors


def main():
    print("=== АНАЛИЗ ОШИБОК ПРОЕКТА ===")
    project_name = os.getenv("PROJECT_NAME", "").strip() or get_project_name()
    print(f"Проект: {project_name}")

    db_dir = _DATA_DIR / project_name / "database"
    if not db_dir.exists():
        print(f"❌ База данных не найдена: {db_dir}")
        return

    errors = collect_errors(project_name)

    if not errors:
        print("\n✅ Ошибок не найдено — всё обработано успешно!")
        return

    by_type  = defaultdict(list)
    by_group = defaultdict(list)
    for e in errors:
        by_type[e['type']].append(e)
        by_group[_group_key(e['source'])].append(e)

    # ── Terminal summary ─────────────────────────────────────────────────────
    SEP = '═' * 54
    print(f"\n{SEP}")
    print(f"  📊 ИТОГО ОШИБОК: {len(errors)}")
    print(f"{SEP}")
    for t, items in sorted(by_type.items()):
        print(f"  {LABELS.get(t, t)}: {len(items)}")

    print(f"\n  По блокам:")
    for grp in sorted(by_group.keys(), key=lambda x: (x in ('upd', '?'), x)):
        items = by_group[grp]
        seen_types = list(dict.fromkeys(x['type'] for x in items))
        types_str = ' / '.join(
            f"{LABELS.get(t, t)}: {sum(1 for x in items if x['type'] == t)}"
            for t in seen_types
        )
        print(f"  {grp:<10} — {len(items):3d} шт.  ({types_str})")

    # ── Save file ────────────────────────────────────────────────────────────
    out_file = db_dir / f"errors_summary_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
    with out_file.open('w', encoding='utf-8') as f:
        f.write(f"ОШИБКИ ПРОЕКТА: {project_name}\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Итого: {len(errors)}\n\n")
        for t, items in sorted(by_type.items()):
            f.write(f"\n{'─'*40}\n")
            f.write(f"{LABELS.get(t, t).upper()} ({len(items)}):\n")
            for e in sorted(items, key=lambda x: x['source']):
                f.write(f"  {e['source']}: {e['url']}\n")

    print(f"\n  💾 Сохранено: {out_file.name}")
    print(SEP)


if __name__ == "__main__":
    main()
