"""Interactive terminal review for work/matches.json.

match_csv.py flags a row "ambiguous" when more than one transcript segment
scores above threshold against it (retakes/dupes), and "unmatched" when none
does. Both flags BLOCK downstream steps (the "ambiguous or unmatched" gate)
until a human confirms/corrects the pick -- this walks through every flagged
row one at a time, shows the candidate(s), and lets you accept or override
with a keypress. Saves after every answer, so it's safe to Ctrl-C and resume
later (already-cleared rows won't be shown again).

Usage:
    uv run helpers/review_matches.py --matches work/matches.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fmt_time(s: float) -> str:
    m, sec = divmod(max(s, 0.0), 60)
    h, m = divmod(int(m), 60)
    return f"{h:02d}:{int(m):02d}:{sec:05.2f}"


def review_ambiguous(matches: list[dict], save) -> None:
    rows = [m for m in matches if m.get("ambiguous")]
    for i, row in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] Строка {row['line_no']}: \"{row['text']}\"")
        for ci, c in enumerate(row["candidates"]):
            mark = "  <- текущий выбор" if ci == row["chosen_index"] else ""
            print(f"  [{ci}] {fmt_time(c['start'])}-{fmt_time(c['end'])} (score {c['score']:.0f}): \"{c['text']}\"{mark}")
        ans = input("Enter = принять текущий выбор, номер = выбрать другой, s = пропустить (разобрать позже): ").strip().lower()
        if ans == "s" or ans == "":
            if ans == "":
                row["ambiguous"] = False
                save()
                print("  ✓ подтверждено (текущий выбор)")
            else:
                print("  · пропущено, останется заблокированной строкой")
            continue
        try:
            n = int(ans)
        except ValueError:
            print("  ! не понял ввод, строка пропущена без изменений")
            continue
        if not (0 <= n < len(row["candidates"])):
            print("  ! нет такого номера, строка пропущена без изменений")
            continue
        row["chosen_index"] = n
        row["ambiguous"] = False
        save()
        print(f"  ✓ выбран вариант [{n}]")


def review_unmatched(matches: list[dict], save) -> None:
    rows = [m for m in matches if m.get("unmatched")]
    for i, row in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] Строка {row['line_no']} (совпадение НЕ найдено): \"{row['text']}\"")
        best = row.get("closest_below_threshold")
        if not best:
            print("  · подходящих кандидатов вообще нет -- карточка для этой строки показана не будет")
            continue
        print(f"  ближайший вариант ниже порога: {fmt_time(best['start'])}-{fmt_time(best['end'])} (score {best['score']:.0f}): \"{best['text']}\"")
        ans = input("y = принять этот вариант, Enter/n = оставить непойманной: ").strip().lower()
        if ans == "y":
            row["candidates"] = [best]
            row["chosen_index"] = 0
            row["unmatched"] = False
            save()
            print("  ✓ принято")
        else:
            print("  · оставлено непойманным -- карточка показана не будет")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", default="work/matches.json")
    args = ap.parse_args()

    path = Path(args.matches)
    matches = json.loads(path.read_text(encoding="utf-8"))

    def save() -> None:
        path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

    n_amb = sum(1 for m in matches if m.get("ambiguous"))
    n_unm = sum(1 for m in matches if m.get("unmatched"))
    print(f"{n_amb} неоднозначных строк, {n_unm} непойманных строк.")
    print("Для каждой: Enter = принять текущий/предложенный вариант, номер/y = выбрать вариант, s/n = пропустить.\n")

    try:
        review_ambiguous(matches, save)
        review_unmatched(matches, save)
    except KeyboardInterrupt:
        print("\n\nПрервано -- уже подтверждённые строки сохранены, остальное можно доразобрать, запустив скрипт ещё раз.")
        raise

    remaining_amb = sum(1 for m in matches if m.get("ambiguous"))
    remaining_unm = sum(1 for m in matches if m.get("unmatched"))
    print(f"\nГотово. Осталось нерешённых: {remaining_amb} неоднозначных, {remaining_unm} непойманных.")
    if remaining_amb or remaining_unm:
        print(
            "Неоднозначные строки пойдут в рендер с предложенным (tentative) вариантом, "
            "непойманные останутся без карточки -- запустите review_matches.py ещё раз, если хотите их доразобрать."
        )
    else:
        print("Все строки разобраны.")


if __name__ == "__main__":
    main()
