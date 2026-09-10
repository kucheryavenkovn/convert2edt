#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDT docker-шим для локального (Windows) режима конвертера.

Вызывается оркестратором как `1cedtcli` (через tools\\1cedtcli.cmd):
переводит пути известных аргументов (-data, --project, --configuration-files)
в маунты docker и запускает 1cedtcli из образа convert2edt/converter.

Используется автоматически, если локальный 1cedtcli недоступен/виснет
(наблюдается на EDT 2026.2 Windows CLI) — см. scripts/local/run-local.ps1.
"""
import shutil
import subprocess
import sys
from pathlib import Path

IMAGE = "convert2edt/converter:latest"
PATH_KEYS = {"-data", "--project", "--configuration-files"}

DRIVE_MAP = {"C": "/c", "D": "/d", "E": "/e"}


def to_posix(path: Path) -> str:
    drive = path.drive.rstrip(":").upper()
    root = DRIVE_MAP.get(drive)
    if root is None:
        raise SystemExit(f"edt-shim: unsupported drive {path.drive}")
    return root + path.as_posix()[2:]


def main() -> int:
    if not shutil.which("docker"):
        sys.stderr.write("edt-shim: docker не найден в PATH\n")
        return 1

    args = sys.argv[1:]
    mounts: list[tuple[Path, str]] = []
    translated: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in PATH_KEYS and i + 1 < len(args[i:]):
            value = args[i + 1]
            path = Path(value)
            if path.is_absolute() and len(path.drive) == 2:
                mounts.append((path if path.is_dir() else path.parent, to_posix(path if path.is_dir() else path.parent)))
                translated.extend([arg, to_posix(path)])
                i += 2
                continue
        translated.append(arg)
        i += 1

    seen: dict[str, str] = {}
    mount_args: list[str] = []
    for host, guest in mounts:
        key = str(host).lower()
        if key not in seen:
            seen[key] = guest
            mount_args.extend(["-v", f"{host}:{guest}"])

    cmd = ["docker", "run", "--rm", *mount_args, IMAGE, "1cedtcli", *translated]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
