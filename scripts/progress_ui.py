#!/usr/bin/env python3
"""Единый вид прогресс-бара для терминала — один обновляемый в строке
индикатор («полосочка») вместо простыни из процентов/скорости/ETA, летящей
построчно. Используется и для скачивания файлов, и для общего прогресса по
шагам/задачам пайплайна.
"""

import sys

BAR_WIDTH = 28


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
            self.stream.write("\r\x1b[K" + line + "\n")
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
        self.stream.write("\r\x1b[K" + text + "\n")
        self.stream.flush()
        self._started = False

    def close(self) -> None:
        self._started = False
