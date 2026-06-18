#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQ_FILE="$ROOT_DIR/requirements.txt"

python_supported() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
import pyexpat  # noqa: F401
import pip  # noqa: F401

sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)
PY
}

requirements_hash() {
  "$1" - "$REQ_FILE" <<'PY'
from pathlib import Path
import hashlib
import sys

path = Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

find_working_python() {
  for candidate in \
    python3.11 \
    /opt/homebrew/opt/python@3.11/bin/python3.11 \
    /usr/local/opt/python@3.11/bin/python3.11 \
    python3.12 \
    /opt/homebrew/opt/python@3.12/bin/python3.12 \
    /usr/local/opt/python@3.12/bin/python3.12 \
    python3.10 \
    /opt/homebrew/opt/python@3.10/bin/python3.10 \
    /usr/local/opt/python@3.10/bin/python3.10 \
    python3.13 \
    python3 \
    python
  do
    if [[ "$candidate" == */* ]]; then
      [[ -x "$candidate" ]] || continue
    elif ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if python_supported "$candidate"; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

install_python() {
  echo "Рабочий Python не найден. Пробую установить Python 3.11..."
  if command -v brew >/dev/null 2>&1; then
    NONINTERACTIVE=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.11
    return
  fi
  echo "Homebrew не найден, Python не установлен автоматически."
  echo "Установите Python 3.11/3.12 вручную или запустите так: PYTHON_BIN=/path/to/python3 ./start.sh"
  exit 1
}

if [[ -n "${PYTHON_BIN:-}" ]]; then
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python не найден: $PYTHON_BIN"
    exit 1
  fi
  if ! python_supported "$PYTHON_BIN"; then
    echo "У выбранного Python неподдерживаемая версия или не работает pip/pyexpat: $PYTHON_BIN"
    echo "Задайте рабочий Python так: PYTHON_BIN=/path/to/python3.11 ./start.sh"
    exit 1
  fi
else
  PYTHON_BIN=""
  if ! find_working_python; then
    install_python
    if ! find_working_python; then
      echo "После установки рабочий Python всё еще не найден."
      exit 1
    fi
  fi
fi

VENV_DIR="$ROOT_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]] || ! python_supported "$VENV_DIR/bin/python"; then
  echo "Создаю локальное окружение Python: $VENV_DIR"
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
PYTHON_BIN="$VENV_DIR/bin/python"
REQ_STAMP="$VENV_DIR/.requirements.sha256"

if [[ ! -f "$REQ_FILE" ]]; then
  echo "Файл зависимостей не найден: $REQ_FILE"
  exit 1
fi

CURRENT_REQ_HASH="$(requirements_hash "$PYTHON_BIN")"
INSTALLED_REQ_HASH="$(cat "$REQ_STAMP" 2>/dev/null || true)"

if [[ "$CURRENT_REQ_HASH" != "$INSTALLED_REQ_HASH" ]]; then
  echo "Устанавливаю зависимости из requirements.txt..."
  "$PYTHON_BIN" -m pip install --disable-pip-version-check -r "$REQ_FILE"
  printf '%s\n' "$CURRENT_REQ_HASH" > "$REQ_STAMP"
fi

export BASE_DIR="$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT_DIR"
if [[ "${1:-}" == "web" ]]; then
  exec "$PYTHON_BIN" "$ROOT_DIR/web/app.py"
else
  exec "$PYTHON_BIN" "$ROOT_DIR/core/main.py"
fi
