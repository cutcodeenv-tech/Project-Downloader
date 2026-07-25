#!/usr/bin/env python3
"""Единый вид терминального интерфейса пайплайна — через rich: цветные
статус-панели («общий прогресс» + «текущая задача»), спиннер для тихих
шагов, единый заголовок стадии/подстадии. Используется и скачиванием
файлов, и сопоставлением CSV, и общим прогрессом по шагам/задачам.
"""

import re
import subprocess
import sys
import threading
import time
from collections import deque

from rich.console import Console
from rich.theme import Theme
from rich.text import Text

BAR_WIDTH = 28
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

THEME = Theme({
    "brand": "bold cyan",
    "accent": "cyan",
    "ok": "bold green",
    "warn": "bold yellow",
    "err": "bold red",
    "muted": "grey62",
    "title": "bold white",
})

console = Console(theme=THEME, highlight=False)


def render_bar(fraction: float, width: int = BAR_WIDTH) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(width * fraction)
    return "█" * filled + "░" * (width - filled)


def print_bar(prefix: str, fraction: float, suffix: str = "", width: int = BAR_WIDTH, stream=None) -> None:
    """Печатает/обновляет индикатор в текущей строке (без перевода строки).
    Вызывать повторно с новым fraction для того же индикатора; завершить
    вызовом finish_bar()."""
    stream = stream or sys.stdout
    bar = render_bar(fraction, width)
    pct = f"{fraction * 100:5.1f}%"
    line = f"{prefix} [{bar}] {pct}"
    if suffix:
        line += f" {suffix}"
    stream.write("\r" + line + " " * 4)
    stream.flush()


def finish_bar(stream=None) -> None:
    stream = stream or sys.stdout
    stream.write("\n")
    stream.flush()


_BAR_RE = re.compile(r"[█░]+")
_PCT_RE = re.compile(r"\d{1,3}(?:\.\d)?%")
_MARK_STYLES = {"✓": "ok", "✅": "ok", "✗": "err", "❌": "err", "⚠": "warn", "⚠️": "warn", "→": "accent", "·": "muted"}
_MARK_RE = re.compile("|".join(re.escape(m) for m in sorted(_MARK_STYLES, key=len, reverse=True)))


def colorize(line: str) -> Text:
    """Раскрашивает уже готовую текстовую строку по простым приметам —
    блочные символы бара, проценты, ведущий значок (✓/✗/→/·/⚠) — так
    существующие вызовы (просто печатающие текст) получают цвет без
    переписывания на структурные виджеты."""
    text = Text(line)
    for m in _BAR_RE.finditer(line):
        bar = m.group(0)
        start = m.start()
        for i, ch in enumerate(bar):
            text.stylize("accent" if ch == "█" else "muted", start + i, start + i + 1)
    for m in _PCT_RE.finditer(line):
        text.stylize("accent", m.start(), m.end())
    m = _MARK_RE.match(line.lstrip())
    if m:
        offset = len(line) - len(line.lstrip())
        style = _MARK_STYLES[m.group(0)]
        text.stylize(style, offset, offset + len(m.group(0)))
    return text


class StatusBoard:
    """Фиксированная панель из нескольких строк (например: имя файла,
    общий прогресс, прогресс текущего файла) — перерисовывается на месте
    через ANSI-коды курсора, а не растёт новыми строками при каждом
    обновлении. В неинтерактивном выводе (не TTY — редирект в файл/лог)
    вместо перерисовки просто печатает снапшот раз в вызов render(),
    чтобы не засорять лог escape-последовательностями."""

    def __init__(self, n_lines: int, stream=None):
        self.n_lines = n_lines
        self.stream = stream or sys.stdout
        self._console = Console(file=self.stream, theme=THEME, highlight=False)
        self._started = False
        self._is_tty = bool(getattr(self.stream, "isatty", lambda: False)())

    def render(self, lines: list) -> None:
        lines = list(lines)[: self.n_lines]
        while len(lines) < self.n_lines:
            lines.append("")

        if not self._is_tty:
            self.stream.write(" | ".join(lines) + "\n")
            self.stream.flush()
            self._started = True
            return

        if self._started:
            self.stream.write(f"\x1b[{self.n_lines}A")
        for line in lines:
            self.stream.write("\r\x1b[K")
            self._console.print(colorize(line))
        self.stream.flush()
        self._started = True

    def log(self, text: str) -> None:
        """Печатает постоянную строку (лог/ошибка/предупреждение) НАД панелью —
        панель остаётся закреплена как последние n_lines строк вывода."""
        if not self._is_tty:
            self.stream.write(text + "\n")
            self.stream.flush()
            self._started = False
            return

        if self._started:
            self.stream.write(f"\x1b[{self.n_lines}A")
        self.stream.write("\r\x1b[K")
        self._console.print(colorize(text))
        self._started = False

    def close(self) -> None:
        self._started = False


def stage_header(project_name: str, stage_number: int, stage_title: str, substep_idx: int, substep_total: int, step_title: str) -> None:
    """Единый заголовок «Проект X — Стадия N — title — подстадия i/n» —
    заменяет разрозненные «=== StageN. Start! ... ===» баннеры по всему
    пайплайну. Печатается один раз перед каждым шагом."""
    console.print(
        f"\n[muted]Проект «{project_name}»[/]   [title]Стадия {stage_number} — {stage_title}[/]   "
        f"[muted]подстадия {substep_idx}/{substep_total}[/]"
    )
    console.print(f"[accent]→[/] {step_title}")


class CommandResult:
    def __init__(self, returncode: int, output: str, elapsed: float):
        self.returncode = returncode
        self.output = output
        self.elapsed = elapsed

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _term_width(default: int = 100) -> int:
    try:
        return max(20, __import__("shutil").get_terminal_size((default, 20)).columns)
    except Exception:
        return default


def run_quiet(cmd, cwd=None, env=None, title=None, stream=None, tail_lines=20) -> CommandResult:
    """Запускает команду со спиннером на одной строке вместо простыни
    сырого вывода: пока процесс работает — крутится спиннер + заголовок
    (+ последняя строка вывода, для ощущения «что-то происходит»). По
    завершении строка стирается и печатается один компактный итог: "✓/✗
    <title> (<Ns>)". Полный вывод не теряется — при ошибке печатаются
    последние tail_lines строк для диагностики. В не-TTY (лог/редирект)
    спиннер не анимируется — просто "… <title>" один раз и итог."""
    stream = stream or sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    out_console = Console(file=stream, theme=THEME, highlight=False)
    label = title or (cmd[0] if isinstance(cmd, (list, tuple)) else str(cmd))

    start = time.monotonic()
    proc = subprocess.Popen(
        [str(part) for part in cmd] if isinstance(cmd, (list, tuple)) else cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    tail = deque(maxlen=tail_lines)
    all_lines = []
    last_line = ""
    lock = threading.Lock()

    def reader():
        nonlocal last_line
        for line in proc.stdout:
            line = line.rstrip("\n")
            with lock:
                tail.append(line)
                all_lines.append(line)
                if line.strip():
                    last_line = line.strip()

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    if not is_tty:
        stream.write(f"… {label}\n")
        stream.flush()

    frame_i = 0
    width = _term_width()
    while proc.poll() is None:
        if is_tty:
            with lock:
                snippet = last_line
            elapsed = time.monotonic() - start
            text_line = f"[accent]{SPINNER_FRAMES[frame_i % len(SPINNER_FRAMES)]}[/] {label} [muted]({elapsed:0.0f}s)[/]"
            if snippet:
                text_line += f" [muted]— {snippet}[/]"
            plain_len = len(f"{SPINNER_FRAMES[frame_i % len(SPINNER_FRAMES)]} {label} ({elapsed:0.0f}s)" + (f" — {snippet}" if snippet else ""))
            if plain_len > width - 1:
                overflow = plain_len - (width - 4)
                snippet = snippet[: max(0, len(snippet) - overflow)] + "..."
                text_line = f"[accent]{SPINNER_FRAMES[frame_i % len(SPINNER_FRAMES)]}[/] {label} [muted]({elapsed:0.0f}s)[/]"
                if snippet:
                    text_line += f" [muted]— {snippet}[/]"
            stream.write("\r\x1b[K")
            out_console.print(text_line, end="")
            stream.flush()
            frame_i += 1
        time.sleep(0.12)

    reader_thread.join(timeout=2)
    returncode = proc.returncode
    elapsed = time.monotonic() - start

    if is_tty:
        stream.write("\r\x1b[K")

    if returncode == 0:
        out_console.print(f"[ok]✓[/] {label} [muted]({elapsed:0.1f}s)[/]")
    else:
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        body = f"[err]Команда завершилась с ошибкой: {returncode}[/]"
        if tail:
            body += "\n\n[muted]  " + "\n  ".join(tail) + "[/]"
        out_console.print(Panel(
            Text.from_markup(body), title=f"✗ {label}", title_align="left",
            border_style="err", box=box.ROUNDED, padding=(1, 2),
        ))
    stream.flush()

    return CommandResult(returncode, "\n".join(all_lines), elapsed)
