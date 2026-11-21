#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разница двух списков диагностик MCP onec: что появилось в ветке, что исчезло.

Сравниваются множества строк: вывод MCP схлопывает дубли и сортирует не так, как
check-modules.log, поэтому количество строк сравнивать нельзя — только состав.

Вход — два текстовых файла с выводом check_configuration или одну строку на
диагностику. Строки нормализуются: снимается префикс списка "- ", уровень
"[error]"/"[warning]", хвостовые пробелы; пустые строки и итоговая строка
"Проверка XML-выгрузки: ..." отбрасываются.

Примеры:
    python .claude/skills/code-review/onec-diff.py build/review/base.txt build/review/current.txt
    python .claude/skills/code-review/onec-diff.py --quiet base.txt current.txt

Коды возврата: 0 — новых диагностик нет, 1 — новые есть, 2 — ошибка вызова или файла.
"""

import argparse
import os
import sys

PREFIXES = ("- [error] ", "- [warning] ", "[error] ", "[warning] ")
SUMMARY_MARKERS = ("Проверка XML-выгрузки", "Проверка выполняется")


def normalize(line):
    """Строка вывода MCP -> диагностика без служебных префиксов."""
    text = line.strip().lstrip("\ufeff")
    for prefix in PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip()


def read_diagnostics(path):
    """Читает файл и возвращает список уникальных диагностик в порядке появления."""
    if not os.path.isfile(path):
        raise OSError("файл не найден: %s" % path)
    seen = set()
    ordered = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as stream:
        for raw in stream:
            text = normalize(raw)
            if not text:
                continue
            if any(marker in text for marker in SUMMARY_MARKERS):
                continue
            if text in ("[error]", "[warning]"):
                continue
            if text not in seen:
                seen.add(text)
                ordered.append(text)
    return ordered


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Разница списков диагностик MCP onec: новые и исчезнувшие строки."
    )
    parser.add_argument("base", help="файл с диагностиками базовой ветки (эталон)")
    parser.add_argument("current", help="файл с диагностиками текущего дерева")
    parser.add_argument("--quiet", action="store_true", help="печатать только итог и новые строки")
    args = parser.parse_args(argv)

    try:
        base = read_diagnostics(args.base)
        current = read_diagnostics(args.current)
    except OSError as error:
        print("ошибка: %s" % error, file=sys.stderr)
        return 2

    base_set = set(base)
    current_set = set(current)
    added = [text for text in current if text not in base_set]
    removed = [text for text in base if text not in current_set]

    if not args.quiet:
        print("База:    %d уникальных диагностик — %s" % (len(base), args.base))
        print("Текущее: %d уникальных диагностик — %s" % (len(current), args.current))
        print("")

    if added:
        print("НОВЫЕ (%d) — замечания ветки:" % len(added))
        for text in added:
            print("  + " + text)
    else:
        print("НОВЫЕ: нет")

    if not args.quiet:
        print("")
        if removed:
            print("ИСЧЕЗЛИ (%d) — вероятно, исправлено в ветке или сменились платформа/режимы:" % len(removed))
            for text in removed:
                print("  - " + text)
        else:
            print("ИСЧЕЗЛИ: нет")

    return 1 if added else 0


if __name__ == "__main__":
    sys.exit(main())
