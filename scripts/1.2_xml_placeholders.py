#!/usr/bin/env python3
"""
1.2_xml_placeholders.py — прозрачный текстовый оверлей поверх РЕАЛЬНОГО (не
вырезанного) хронометража озвучки: для каждой строки CSV-сценария показывает
её текст (+ доп. поля вроде A/B/C) точно в момент, когда она звучит.

Использует пайплайн text-overlay-align (сопоставление CSV со словами
транскрипта через rapidfuzz, тайминги по словам из Whisper) — но БЕЗ
«плотной» склейки: пауза остаётся паузой, аудио не режется, оверлей просто
показывает нужную карточку в нужный момент оригинальной записи.

На вход:
  - CSV-сценарий (последний input_gdoc*.csv в database/) со столбцом текста
    (заголовок содержит "текст"/"text"); остальные столбцы (A/B/C, ...) идут
    доп. полями на карточке.
  - Аудио озвучки в voiceover/ (транскрибируется Whisper с пословными
    таймкодами; если уже есть <файл>.words.json — используется он).

На выход (папка placeholders_xml/):
  - overlay.mov — прозрачный (QuickTime Animation/alpha) оверлей на весь
    хронометраж записи.
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
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from path_utils import get_data_dir, project_subdir, resolve_project_name
from progress_ui import run_quiet
import manifest

TOOL_DIR = SCRIPT_DIR / "text_overlay_align"
HELPERS_DIR = TOOL_DIR / "helpers"

WHISPER_MODEL_DEFAULT = "base"


def _find_audio(voiceover_dir: Path):
    """Авто-поиск аудиофайла для транскрипции (wav, mp3, m4a, flac, ogg)."""
    for ext in ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.ogg"):
        matches = sorted(glob.glob(str(voiceover_dir / ext)))
        if matches:
            return matches[-1]
    return None


def _find_cached_words_json(voiceover_dir: Path):
    matches = sorted(glob.glob(str(voiceover_dir / "*.words.json")))
    return matches[-1] if matches else None


def _find_legacy_transcript(voiceover_dir: Path):
    """.srt/.txt — используется только если нет аудио для Whisper (тогда
    пословных таймкодов не будет, сопоставление грубее — на уровне фраз)."""
    for ext in ("*.srt", "*.txt"):
        matches = sorted(glob.glob(str(voiceover_dir / ext)))
        if matches:
            return matches[-1]
    return None


def _install_whisper() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        pass
    print("⬇️  openai-whisper не найден — устанавливаю...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--prefer-binary", "openai-whisper"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"❌ Не удалось установить whisper:\n{(r.stderr or r.stdout)[-400:]}")
        return False
    print("✅ openai-whisper установлен")
    return True


def _transcribe_words(audio_path: str, voiceover_dir: Path, model_name: str, language: str):
    """Whisper с пословными таймкодами → <стем>.words.json в voiceover_dir."""
    if not _install_whisper():
        return None
    import whisper

    print(f"🎙  Транскрибирую (по словам): {os.path.basename(audio_path)}")
    print(f"    Модель: {model_name}  Язык: {language or 'авто'}")
    try:
        model = whisper.load_model(model_name)
        opts = {"verbose": False, "word_timestamps": True}
        if language:
            opts["language"] = language
        result = model.transcribe(audio_path, **opts)
    except Exception as exc:
        print(f"❌ Ошибка Whisper: {exc}")
        return None

    segments = []
    for seg in result.get("segments", []):
        words = [
            {"word": w.get("word", "").strip(), "start": float(w["start"]), "end": float(w["end"])}
            for w in (seg.get("words") or [])
            if w.get("word", "").strip()
        ]
        segments.append({
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": (seg.get("text") or "").strip(),
            "words": words,
        })

    stem = Path(audio_path).stem
    out_path = voiceover_dir / f"{stem}.words.json"
    try:
        out_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ Транскрипция (по словам) сохранена: {out_path}")
        return str(out_path)
    except Exception as exc:
        print(f"❌ Не удалось сохранить транскрипт: {exc}")
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

    whisper_model = os.getenv("WHISPER_MODEL", "").strip() or WHISPER_MODEL_DEFAULT
    whisper_language = os.getenv("WHISPER_LANGUAGE", "").strip()

    transcript_json = os.getenv("TRANSCRIPT_FILE", "").strip()
    if transcript_json and not os.path.isfile(transcript_json):
        transcript_json = ""
    if not transcript_json:
        transcript_json = _find_cached_words_json(voiceover_dir)

    legacy_transcript = None
    if not transcript_json:
        audio_path = _find_audio(voiceover_dir)
        if audio_path:
            transcript_json = _transcribe_words(audio_path, voiceover_dir, whisper_model, whisper_language)
        else:
            legacy_transcript = _find_legacy_transcript(voiceover_dir)

    transcript_path = transcript_json or legacy_transcript
    if not transcript_path:
        print(
            f"⏭️  Пропускаю шаг текстового оверлея: нет аудио и нет расшифровки в {voiceover_dir}\n"
            "   Положите .wav/.mp3 (для Whisper) или .srt/.txt в папку voiceover/ проекта."
        )
        return

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
    if ambiguous or unmatched:
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        from progress_ui import console

        body = f"[warn]Требуется проверка: неоднозначных строк {len(ambiguous)}, непойманных {len(unmatched)}.[/]"
        if match_result and match_result.output.strip():
            body += "\n\n[muted]" + match_result.output.strip() + "[/]"
        body += f"\n\n[muted]Откройте {matches_path} и поправьте \"chosen_index\" у неоднозначных строк, затем запустите этот шаг ещё раз.[/]"
        console.print(Panel(
            Text.from_markup(body), title="⚠ Текстовый оверлей", title_align="left",
            border_style="warn", box=box.ROUNDED, padding=(1, 2),
        ))
        sys.exit(2)

    if not _run_helper("build_timing_uncut.py", "--matches", matches_path, "--out", timing_path, title="Построение таймингов").ok:
        sys.exit("❌ Не удалось построить тайминги оверлея.")

    overlay_path = out_dir / "overlay.mov"
    cards_dir = work_dir / "cards"
    clips_dir = work_dir / "overlay_clips"
    if not _run_helper(
        "render_overlay.py",
        "--timing", timing_path,
        "--cards-dir", cards_dir,
        "--clips-dir", clips_dir,
        "--out", overlay_path,
        title="Рендер оверлея",
    ).ok:
        sys.exit("❌ Не удалось отрендерить оверлей.")

    print(f"✅ Готово: {overlay_path}")


if __name__ == "__main__":
    main()
