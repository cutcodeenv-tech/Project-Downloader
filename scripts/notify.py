#!/usr/bin/env python3
"""Уведомления о завершении прогона: системное уведомление macOS и,
если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (меню «Настройки» или
.env), сообщение в Telegram. Ошибки отправки не роняют пайплайн.

Как получить TELEGRAM_CHAT_ID: напишите своему боту любое сообщение и
откройте https://api.telegram.org/bot<TOKEN>/getUpdates — там будет
"chat":{"id":...}.
"""

import os
import platform
import subprocess

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def notifications_enabled() -> bool:
    return (os.getenv("NOTIFY") or "on").strip().lower() != "off"


def _macos_notification(title: str, message: str) -> None:
    if platform.system() != "Darwin":
        return
    def quote(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{quote(message)}" with title "{quote(title)}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _telegram(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id or requests is None:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        return response.ok
    except Exception:
        return False


def notify(title: str, message: str) -> None:
    if not notifications_enabled():
        return
    _macos_notification(title, message)
    _telegram(f"{title}\n{message}")


def _format_duration(seconds: float) -> str:
    minutes = int(seconds) // 60
    if minutes < 1:
        return f"{int(seconds)} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


def notify_flow_finished(project_name: str, results: dict, elapsed: float) -> None:
    """Короткая сводка прогона. Совсем короткие прогоны (меньше минуты)
    не беспокоят — пользователь и так смотрит в терминал."""
    if elapsed < 60:
        return
    failed = sum(1 for status in results.values() if status in ("failed", "blocked"))
    done = sum(1 for status in results.values() if status in ("done", "skipped"))
    if failed:
        title = f"⚠️ «{project_name}»: готово с ошибками"
        message = f"Шагов выполнено: {done}, с ошибками: {failed}. Время: {_format_duration(elapsed)}"
    else:
        title = f"✅ «{project_name}» готов"
        message = f"Шагов выполнено: {done}. Время: {_format_duration(elapsed)}"
    notify(title, message)
