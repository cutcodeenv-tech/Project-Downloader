import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

API_BASE = "https://api.krea.ai"
ASSETS_ENDPOINT = f"{API_BASE}/assets"
REQUEST_TIMEOUT = 30


def load_krea_token(base_dir: Path) -> str:
    load_dotenv(base_dir / ".env")
    return (os.getenv("KREA_API_TOKEN") or os.getenv("KREA_TOKEN") or "").strip()


def main() -> int:
    base_dir = Path(__file__).resolve().parent.parent
    token = load_krea_token(base_dir)

    if not token:
        print("❌ Krea API token не найден.")
        print("Добавьте KREA_API_TOKEN в .env или в переменные окружения.")
        return 1

    try:
        response = requests.get(
            ASSETS_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        print(f"❌ Не удалось подключиться к Krea API: {exc}")
        return 1

    if response.status_code == 200:
        print("✓ Krea API доступен, токен валиден")
        return 0

    if response.status_code == 401:
        print("❌ Krea API token недействителен или истек")
        return 1

    if response.status_code == 402:
        print("❌ Krea API отклонил запрос: недостаточно биллинга/кредитов")
        return 1

    print(f"❌ Krea API вернул неожиданный статус: {response.status_code}")
    try:
        print(response.text[:1000])
    except Exception:
        pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
