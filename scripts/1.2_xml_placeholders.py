#!/usr/bin/env python3
"""
1.2_xml_placeholders.py — прозрачный текстовый оверлей поверх РЕАЛЬНОГО (не
вырезанного) хронометража озвучки: для каждой строки CSV-сценария показывает
её текст (+ доп. поля вроде A/B/C) точно в момент, когда она звучит.

Использует пайплайн text-overlay-align (сопоставление CSV со словами
транскрипта через rapidfuzz) — но БЕЗ «плотной» склейки: пауза остаётся
паузой, аудио не режется, оверлей просто показывает нужную карточку в нужный
момент оригинальной записи.

На вход:
  - CSV-сценарий (последний input_gdoc*.csv в database/) со столбцом текста
    (заголовок содержит "текст"/"text"); остальные столбцы (A/B/C, ...) идут
    доп. полями на карточке.
  - Готовая расшифровка озвучки в voiceover/: <файл>.words.json (пословные
    таймкоды, например от Whisper — транскрибируется ОТДЕЛЬНЫМ шагом, не
    этим скриптом) или .srt/.txt (тайминги на уровне фраз, сопоставление
    грубее). Этот шаг транскрипцию сам не делает.

На выход (папка placeholders_xml/):
  - overlay_clips/ — по одному прозрачному (QuickTime Animation/alpha)
    .mov-фрагменту на каждую строку CSV (без финальной склейки в один файл).
  - _work/ — промежуточные segments.json / matches.json / timing.json.

Неоднозначные/непойманные строки: скрипт останавливается и печатает отчёт
вместо рендера. Отредактируйте "chosen_index" в _work/matches.json и
запустите этот шаг ещё раз — если CSV и расшифровка не изменились,
сопоставление не будет пересчитано заново, и ваша правка сохранится.

Запуск из терминального пайплайна (PROJECT_NAME задан автоматически).
Ручной запуск: PROJECT_NAME=<проект> python3 1.2_xml_placeholders.py
"""

import glob
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from path_utils import get_data_dir, project_subdir, resolve_project_name
from progress_ui import run_quiet
import manifest

TOOL_DIR = SCRIPT_DIR / "text_overlay_align"
HELPERS_DIR = TOOL_DIR / "helpers"


def _find_cached_words_json(voiceover_dir: Path):
    """Готовая пословная расшифровка (например, из отдельного шага Whisper)."""
    matches = sorted(glob.glob(str(voiceover_dir / "*.words.json")))
    return matches[-1] if matches else None


def _find_legacy_transcript(voiceover_dir: Path):
    """.srt/.txt — тайминги на уровне фраз, сопоставление грубее (без
    пословных таймкодов)."""
    for ext in ("*.srt", "*.txt"):
        matches = sorted(glob.glob(str(voiceover_dir / ext)))
        if matches:
            return matches[-1]
    return None


def _run_helper(name: str, *args, title=None):
    cmd = [sys.executable, str(HELPERS_DIR / name), *[str(a) for a in args]]
    return run_quiet(cmd, cwd=str(TOOL_DIR), title=title or name)


def main():
    project_name = os.getenv("PROJECT_NAME", "").strip() or resolve_project_name()
    data_dir = get_data_dir(__file__)
    project_dir = data_dir / project_name

    db_dir = project_subdir(project_dir, "database")
    voiceover_dir = project_subdir(project_dir, "voiceover")
    out_dir = project_subdir(project_dir, "placeholders_xml")

    csv_candidates = sorted(glob.glob(str(db_dir / "input_gdoc*.csv")))
    if not csv_candidates:
        sys.exit(
            f"❌ CSV не найден в {db_dir}\n"
            "   Сначала запустите «Парсинг Google таблицы»."
        )
    csv_path = csv_candidates[-1]

    transcript_json = os.getenv("TRANSCRIPT_FILE", "").strip()
    if transcript_json and not os.path.isfile(transcript_json):
        transcript_json = ""
    if not transcript_json:
        transcript_json = _find_cached_words_json(voiceover_dir)

    transcript_path = transcript_json or _find_legacy_transcript(voiceover_dir)
    if not transcript_path:
        sys.exit(
            f"❌ Нет готовой расшифровки в {voiceover_dir}\n"
            "   Положите туда <файл>.words.json (пословные таймкоды, например от\n"
            "   отдельного шага транскрипции) или .srt/.txt, затем запустите этот шаг ещё раз."
        )

    transcript_format = "json" if transcript_path.lower().endswith(".json") else (
        "srt" if transcript_path.lower().endswith(".srt") else "lines"
    )

    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    segments_path = work_dir / "segments.json"
    matches_path = work_dir / "matches.json"
    timing_path = work_dir / "timing.json"

    print("=== ТЕКСТОВЫЙ ОВЕРЛЕЙ (text-overlay-align, без склейки) ===")
    print(f"  Проект:      {project_name}")
    print(f"  CSV:         {os.path.basename(csv_path)}")
    print(f"  Расшифровка: {os.path.basename(transcript_path)}")
    print(f"  Выход:       {out_dir}")

    match_result = None
    if manifest.is_stale(matches_path):
        if not _run_helper("parse_transcript.py", transcript_path, "--format", transcript_format, "--out", segments_path, title="Разбор расшифровки").ok:
            sys.exit("❌ Не удалось разобрать расшифровку.")

        match_result = _run_helper("match_csv.py", csv_path, "--segments", segments_path, "--out", matches_path, title="Сопоставление CSV со словами")
        if not match_result.ok:
            sys.exit("❌ Не удалось сопоставить CSV с расшифровкой.")

        _run_helper("rescue_unmatched.py", "--segments", segments_path, "--matches", matches_path, "--out", matches_path, title="Спасение непойманных строк")
        _run_helper("refine_word_boundaries.py", "--segments", segments_path, "--matches", matches_path, "--out", matches_path, title="Уточнение границ по словам")

        manifest.write_manifest(matches_path, [csv_path, transcript_path])
    else:
        print(f"♻️  {matches_path.name} не устарел (CSV и расшифровка не менялись) — использую как есть.")
        print("   (если вы правили \"chosen_index\" вручную — правки сохранены)")

    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    ambiguous = [m for m in matches if m.get("ambiguous")]
    unmatched = [m for m in matches if m.get("unmatched")]
    force_proceed = os.getenv("TEXT_OVERLAY_FORCE", "").strip() == "1"
    if (ambiguous or unmatched) and not force_proceed:
        # Exit code 3 is a distinct sentinel (not a real failure): the
        # caller (core/main.py's create_xml_placeholders) catches it,
        # launches helpers/review_matches.py interactively so the operator
        # can confirm/correct each row right there, then re-runs this
        # script with TEXT_OVERLAY_FORCE=1 so it proceeds no matter what's
        # left unresolved after that one review pass (see below).
        print(f"⚠️  Требуется проверка: неоднозначных строк {len(ambiguous)}, непойманных {len(unmatched)}.")
        sys.exit(3)

    if ambiguous or unmatched:
        print(
            f"⚠️  Продолжаю без полного разбора: {len(ambiguous)} неоднозначных строк "
            "берут предложенный (tentative) вариант, "
            f"{len(unmatched)} непойманных останутся без карточки."
        )

    if not _run_helper("build_timing_uncut.py", "--matches", matches_path, "--out", timing_path, title="Построение таймингов").ok:
        sys.exit("❌ Не удалось построить тайминги оверлея.")

    cards_dir = work_dir / "cards"
    clips_dir = out_dir / "overlay_clips"
    if not _run_helper(
        "render_overlay.py",
        "--timing", timing_path,
        "--cards-dir", cards_dir,
        "--clips-dir", clips_dir,
        title="Рендер оверлея",
    ).ok:
        sys.exit("❌ Не удалось отрендерить оверлей.")

    print(f"✅ Готово: {clips_dir} ({len(list(clips_dir.glob('*.mov')))} фрагмент(ов))")


if __name__ == "__main__":
    main()
