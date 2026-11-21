#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Инвентарь изменений ветки для код-ревью 1С-конфигурации.

Печатает базу сравнения и merge-base, коммиты ветки, изменённые модули BSL с построчными
итогами и изменениями сигнатур "Экспорт", изменения метаданных XML, правки документации
и инструментов, предупреждения (вендорские модули БСП, .bin, удалённые файлы,
неотслеживаемые файлы).

Скрипт только читает репозиторий и рабочие файлы, ничего не меняет.

Примеры:
    python .claude/skills/code-review/digest.py
    python .claude/skills/code-review/digest.py --base feat/GRACE_Rework
    python .claude/skills/code-review/digest.py --files
"""

import argparse
import os
import re
import subprocess
import sys

KIND_NAMES = {
    "AccumulationRegisters": "РегистрНакопления",
    "AccountingRegisters": "РегистрБухгалтерии",
    "BusinessProcesses": "БизнесПроцесс",
    "CalculationRegisters": "РегистрРасчета",
    "Catalogs": "Справочник",
    "ChartsOfAccounts": "ПланСчетов",
    "ChartsOfCalculationTypes": "ПланВидовРасчета",
    "ChartsOfCharacteristicTypes": "ПланВидовХарактеристик",
    "CommandGroups": "ГруппаКоманд",
    "CommonAttributes": "ОбщийРеквизит",
    "CommonCommands": "ОбщаяКоманда",
    "CommonForms": "ОбщаяФорма",
    "CommonModules": "ОбщийМодуль",
    "CommonPictures": "ОбщаяКартинка",
    "CommonTemplates": "ОбщийМакет",
    "Constants": "Константа",
    "DataProcessors": "Обработка",
    "DefinedTypes": "ОпределяемыйТип",
    "DocumentJournals": "ЖурналДокументов",
    "Documents": "Документ",
    "Enums": "Перечисление",
    "EventSubscriptions": "ПодпискаНаСобытие",
    "ExchangePlans": "ПланОбмена",
    "FilterCriteria": "КритерийОтбора",
    "FunctionalOptions": "ФункциональнаяОпция",
    "FunctionalOptionsParameters": "ПараметрФункциональныхОпций",
    "InformationRegisters": "РегистрСведений",
    "Interfaces": "Интерфейс",
    "Languages": "Язык",
    "Reports": "Отчет",
    "Roles": "Роль",
    "ScheduledJobs": "РегламентноеЗадание",
    "SessionParameters": "ПараметрСеанса",
    "SettingsStorages": "ХранилищеНастроек",
    "StyleItems": "ЭлементСтиля",
    "Subsystems": "Подсистема",
    "Tasks": "Задача",
    "WebServices": "WebСервис",
    "XDTOPackages": "ПакетXDTO",
}

VENDOR_PATCHES = ("УправлениеПечатью",)
OWN_PREFIXES = ("ВетИС_", "кб99_", "ВСД")

RE_EXPORT = re.compile(
    r"^\s*(?:Процедура|Функция)\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\s*\(.*\)\s*Экспорт\b"
)

STATUS_RU = {
    "A": "добавлен",
    "M": "изменён",
    "D": "удалён",
    "R": "переименован",
    "C": "скопирован",
    "T": "сменил тип",
}


def run_git(repo, args):
    """Возвращает stdout git. Бросает RuntimeError с текстом ошибки git."""
    command = ["git", "-C", repo, "-c", "core.quotepath=false", "-c", "color.ui=false"] + args
    process = subprocess.run(command, capture_output=True)
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError("git %s: %s" % (" ".join(args), message))
    return process.stdout.decode("utf-8", "replace")


def ref_exists(repo, ref):
    process = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        capture_output=True,
    )
    return process.returncode == 0


def repo_root(explicit):
    start = explicit or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    process = subprocess.run(
        ["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True
    )
    if process.returncode != 0:
        raise RuntimeError("не удалось определить корень репозитория от %s" % start)
    return process.stdout.decode("utf-8", "replace").strip()


def resolve_base(repo, explicit):
    if explicit:
        if not ref_exists(repo, explicit):
            raise RuntimeError("база сравнения не найдена: %s" % explicit)
        return explicit
    for candidate in ("origin/dev", "dev", "origin/master", "master"):
        if ref_exists(repo, candidate):
            return candidate
    raise RuntimeError("не найдена база сравнения, укажите --base <ветка>")


def parse_object(path):
    """unload/cf/<Kind>/<Name>/... -> (вид, имя, хвост пути)."""
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "unload" and parts[1] == "cf":
        kind_dir = parts[2]
        if kind_dir in KIND_NAMES:
            return KIND_NAMES[kind_dir], parts[3], "/".join(parts[4:])
        return kind_dir, parts[3] if len(parts) > 3 else "", "/".join(parts[4:])
    return None, None, path


def module_kind(kind_ru, tail):
    if kind_ru == "ОбщийМодуль":
        return "общий модуль"
    name = tail.rsplit("/", 1)[-1]
    if tail.endswith("Ext/Module.bsl"):
        return "модуль объекта"
    if tail.endswith("Ext/ManagerModule.bsl"):
        return "модуль менеджера"
    if tail.endswith("Ext/RecordSetModule.bsl"):
        return "модуль набора записей"
    if tail.endswith("Ext/CommandModule.bsl"):
        return "модуль команды"
    if tail.endswith("Ext/ValueManagerModule.bsl"):
        return "модуль менеджера значения"
    if "/Ext/Form/Module.bsl" in tail or tail.startswith("Ext/Form/Module.bsl"):
        return "модуль формы"
    return name


def is_vendor(path, kind_ru, name):
    if kind_ru != "ОбщийМодуль":
        return False
    if name in VENDOR_PATCHES:
        return False
    return not name.startswith(OWN_PREFIXES)


def has_grace_header(full_path):
    try:
        with open(full_path, "r", encoding="utf-8-sig", errors="replace") as stream:
            head = "".join([next(stream, "") for _ in range(40)])
    except OSError:
        return None
    return "GRACE:MODULE_START" in head


def export_changes(repo, base, path):
    """Добавленные и удалённые экспортные методы по диффу файла."""
    try:
        diff = run_git(repo, ["diff", "--no-renames", "-U0", base, "--", path])
    except RuntimeError:
        return [], []
    added, removed = [], []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            match = RE_EXPORT.match(line[1:])
            if match:
                added.append(match.group(1))
        elif line.startswith("-"):
            match = RE_EXPORT.match(line[1:])
            if match:
                removed.append(match.group(1))
    return added, removed


def collect(repo, base):
    merge_base = run_git(repo, ["merge-base", base, "HEAD"]).strip() or base
    branch = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    head = run_git(repo, ["rev-parse", "--short", "HEAD"]).strip()

    name_status = {}
    for line in run_git(repo, ["diff", "--no-renames", "--name-status", merge_base]).splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) >= 2:
            name_status[fields[-1]] = fields[0][:1]

    numstat = {}
    for line in run_git(repo, ["diff", "--no-renames", "--numstat", merge_base]).splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        path = fields[2]
        try:
            numstat[path] = (int(fields[0]), int(fields[1]))
        except ValueError:
            numstat[path] = None

    dirty = set()
    untracked = []
    for line in run_git(repo, ["status", "--porcelain", "-uall"]).splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if line.startswith("??"):
            if path.startswith(".claude/skills/code-review/"):
                # сам скрипт ревью: пока не закоммичен, он не является изменением ветки
                continue
            untracked.append(path)
        else:
            dirty.add(path)

    commits = int(run_git(repo, ["rev-list", "--count", merge_base + "..HEAD"]).strip() or 0)
    base_sha = run_git(repo, ["rev-parse", "--short", base]).strip() if ref_exists(repo, base) else "?"
    base_date = run_git(repo, ["show", "-s", "--format=%cs", merge_base]).strip()

    return {
        "branch": branch,
        "head": head,
        "base": base,
        "base_sha": base_sha,
        "merge_base": merge_base[:8],
        "base_date": base_date,
        "commits": commits,
        "status": name_status,
        "numstat": numstat,
        "dirty": dirty,
        "untracked": untracked,
    }


def print_header(repo, data):
    total_add = sum(v[0] for v in data["numstat"].values() if v)
    total_del = sum(v[1] for v in data["numstat"].values() if v)
    print("Ветка:  %s (HEAD %s)" % (data["branch"], data["head"]))
    print(
        "База:   %s (%s), merge-base %s от %s"
        % (data["base"], data["base_sha"], data["merge_base"], data["base_date"])
    )
    print("Коммитов в ветке: %d" % data["commits"])
    print(
        "Изменено файлов: %d (+%d / -%d); незакоммиченных: %d; неотслеживаемых: %d"
        % (len(data["status"]), total_add, total_del, len(data["dirty"]), len(data["untracked"]))
    )


def print_files(data):
    rows = sorted(data["status"].items(), key=lambda item: item[0])
    width = max([len(path) for path in data["status"]] or [10])
    for path, status in rows:
        stats = data["numstat"].get(path)
        numbers = "+%d/-%d" % stats if stats else "bin"
        mark = "*" if path in data["dirty"] else " "
        print(("%s %-14s %-11s %-*s" % (status, STATUS_RU.get(status, status), numbers, width, path)).rstrip())


def print_report(repo, data):
    bsl, xml, other = [], [], []
    warnings = []

    for path in sorted(data["status"]):
        status = data["status"][path]
        kind_ru, name, tail = parse_object(path)
        stats = data["numstat"].get(path)
        if path.endswith(".bsl"):
            bsl.append((path, status, kind_ru, name, tail, stats))
        elif path.startswith("unload/cf/"):
            xml.append((path, status, kind_ru, name, stats))
        else:
            other.append((path, status, stats))

        if path.endswith(".bin"):
            warnings.append("двоичный модуль в диффе: %s (защищённая поставка — сверить с .bsl)" % path)
        if status == "D":
            warnings.append("удалён файл: %s" % path)
        if path.startswith("unload/cf/Ext/"):
            warnings.append("изменён корневой модуль конфигурации: %s" % path)
        if kind_ru == "ОбщийМодуль" and name in VENDOR_PATCHES:
            warnings.append("изменён модуль, зафиксированный как патч: %s (проверить объём правки)" % name)
        elif is_vendor(path, kind_ru, name):
            warnings.append("вендорский общий модуль БСП изменён: %s (AGENTS.md, раздел 3.3)" % name)

    print("")
    print("--- Модули BSL (%d) ---" % len(bsl))
    if not bsl:
        print("  нет")
    for path, status, kind_ru, name, tail, stats in bsl:
        numbers = "+%d/-%d" % stats if stats else "bin"
        mark = " *" if path in data["dirty"] else ""
        print("%-7s %-11s %s  [%s]%s" % (status, numbers, "%s.%s" % (kind_ru or "?", name), module_kind(kind_ru, tail), mark))
        print("          %s" % path)
        added, removed = export_changes(repo, data["merge_base"], path)
        if added or removed:
            parts = []
            if added:
                parts.append("добавлен " + ", ".join(sorted(set(added))))
            if removed:
                parts.append("удалён " + ", ".join(sorted(set(removed))))
            print("          Экспорт: " + "; ".join(parts))
        if kind_ru == "ОбщийМодуль" and not is_vendor(path, kind_ru, name):
            full_path = os.path.join(repo, path.replace("/", os.sep))
            if has_grace_header(full_path) is False:
                print("          GRACE-шапки нет (AGENTS.md, раздел 5)")

    print("")
    print("--- Метаданные XML (%d) ---" % len(xml))
    if not xml:
        print("  нет")
    for path, status, kind_ru, name, stats in xml:
        if path.endswith(("Configuration.xml", "ConfigDumpInfo.xml")) or kind_ru is None:
            print("%-7s %s" % (status, path))
        else:
            print("%-7s %s.%s" % (status, kind_ru, name))
            print("          %s" % path)

    print("")
    print("--- Документация, инструменты, прочее (%d) ---" % len(other))
    if not other:
        print("  нет")
    for path, status, stats in other:
        numbers = " (+%d/-%d)" % stats if stats else ""
        print("%-7s %s%s" % (status, path, numbers))

    if data["untracked"]:
        print("")
        print("--- Не отслеживается git (%d) ---" % len(data["untracked"]))
        for path in data["untracked"]:
            print("?       %s" % path)

    print("")
    print("--- Предупреждения (%d) ---" % len(warnings))
    if not warnings:
        print("  нет")
    for text in warnings:
        print("! " + text)

    if data["status"] and not bsl and not xml:
        print("")
        print("Изменения не затрагивают код конфигурации: ревью — по согласованности документов и инструментов.")

    print("")
    print("Обозначения: * — незакоммиченные правки в файле; bin — двоичный файл без построчной статистики.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Инвентарь изменений ветки для код-ревью 1С-конфигурации (только чтение)."
    )
    parser.add_argument("--base", help="база сравнения: ветка или коммит (по умолчанию origin/dev, иначе dev)")
    parser.add_argument("--repo", help="корень репозитория (по умолчанию — каталог скрипта на три уровня выше)")
    parser.add_argument("--files", action="store_true", help="полный список путей со статусами и построчными итогами")
    args = parser.parse_args(argv)

    try:
        repo = repo_root(args.repo)
        base = resolve_base(repo, args.base)
        data = collect(repo, base)
    except RuntimeError as error:
        print("ошибка: %s" % error, file=sys.stderr)
        return 2

    if not data["status"] and not data["untracked"]:
        print("Изменений относительно %s нет." % base)
        return 0

    print_header(repo, data)
    if args.files:
        print("")
        print_files(data)
    else:
        print_report(repo, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
