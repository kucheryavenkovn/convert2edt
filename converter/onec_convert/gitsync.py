"""Движок gitsync: хранилище 1С -> git через oscript-library/gitsync.

Альтернатива нативному конвейеру (ctool1cd + ibcmd + 1cedtcli):
  * версии хранилища читает КОНФИГУРАТОР 1С (1cv8 DESIGNER), не ctool1cd;
  * XML -> EDT делает плагин gitsync `edtExport` (>= 2.0.1, через 1cedtcli);
  * git-историю (коммиты, авторы из AUTHORS, даты) формирует сам gitsync.

Особенности (проверено локально, см. scripts/local/run-gitsync.ps1):
  * workdir проекта ДОЛЖЕН с первого запуска содержать каталог `src`
    (issue oscript-library/gitsync-plugins#53): gitsync кладёт исходники в
    WORKDIR/src, если тот существует; EDT-проект живёт в src стабильно;
  * `gitsync init` конфликтует с edtExport (project-name не зарегистрирован
    для init) — на время init плагин отключается и включается обратно;
  * OneScript 1.9.4: задание OSCRIPT_CONFIG=lib.additional выключает поиск
    библиотек в <gitsync>/oscript_modules — run-gitsync.ps1 зеркалит нужные
    пакеты (json, gitrunner, edtfind и др.) в tools/oscript/oscript_modules;
    здесь каталог просто подхватывается, если существует.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from time import monotonic

from .env import Config
from .pipeline import STATS_FILE, append_stats, new_stats_run
from .proc import info, run_tool

EDT_EXPORT_PLUGIN = "edtExport"

# Маркер начала обработки версии в выводе gitsync sync:
#   "ИНФОРМАЦИЯ - Получаем исходники для версии 1, 11.09.2026 4:41:36"
# Кириллица зависит от кодировки консоли (OEM/UTF-8) — матчимся только по
# ASCII-части: номер версии + дата/время в конце строки.
VERSION_MARKER = re.compile(r"(\d+), \d{2}\.\d{2}\.\d{4} \d{1,2}:\d{2}:\d{2}\s*$")


class GitSyncError(RuntimeError):
    pass


def _echo(line: str) -> None:
    """Печать строки лога gitsync; консоль Windows (cp1251) может не принять
    часть символов вывода EDT — заменяем их, а не роняем прогон."""
    try:
        print(line, end="", flush=True)
    except UnicodeEncodeError:
        out = sys.stdout
        out.buffer.write(line.encode(out.encoding or "utf-8", "replace"))
        out.flush()


def _repo_tools_oslib() -> Path | None:
    # converter/onec_convert/gitsync.py -> <repo>/tools/oscript/oscript_modules
    repo_root = Path(__file__).resolve().parents[2]
    oslib = repo_root / "tools" / "oscript" / "oscript_modules"
    return oslib if oslib.is_dir() else None


class GitSync:
    """Тонкая обёртка над CLI gitsync (OneScript) с плагином edtExport."""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.bin = shutil.which("gitsync")
        if not self.bin:
            raise GitSyncError(
                "gitsync не найден в PATH (нужны OneScript и пакет gitsync: "
                "opm install gitsync; плагин: gitsync plugins enable edtExport)"
            )

    def _env(self, project_name: str, workspace: Path) -> dict:
        env = dict(os.environ)
        env["GITSYNC_PROJECT_NAME"] = project_name
        env["GITSYNC_WORKSPACE_LOCATION"] = str(workspace)
        oslib = _repo_tools_oslib()
        if oslib is not None:
            env["OSCRIPT_CONFIG"] = f"lib.additional={oslib}"
        return env

    def _run(self, args: list[str], env: dict) -> None:
        result = subprocess.run([self.bin, *args], env=env)
        if result.returncode != 0:
            raise GitSyncError(f"gitsync {args[0] if args else ''} exited with code {result.returncode}")

    def _run_logged(self, args: list[str], env: dict) -> tuple[list[tuple[int, float]], float]:
        """Прогнать gitsync, транслируя вывод и собирая таймстемпы версий.

        Внутренние фазы gitsync (дамп/XML/EDT) извне недоступны — замеряем
        длительность обработки каждой версии целиком по маркерам
        «Получаем исходники для версии N» в логе.
        """
        markers: list[tuple[int, float]] = []
        start = monotonic()
        proc = subprocess.Popen(
            [self.bin, *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _echo(line)
            marker = VERSION_MARKER.search(line)
            if marker:
                markers.append((int(marker.group(1)), monotonic()))
        code = proc.wait()
        if code != 0:
            raise GitSyncError(f"gitsync {args[0] if args else ''} exited with code {code}")
        return markers, monotonic() - start

    def _plugins(self, action: str, env: dict) -> None:
        self._run(["plugins", action, EDT_EXPORT_PLUGIN], env)

    def _ensure_git_repo(self, workdir: Path) -> None:
        # gitsync init может не создать .git; worktree внутри другого
        # репозитория тогда подхватывает чужой .gitignore — страхуемся
        if not (workdir / ".git").exists():
            run_tool(["git", "-C", str(workdir), "init", "-q"])

    def sync_project(
        self,
        storage: str,
        workdir: Path,
        project_name: str,
        storage_user: str = "Администратор",
        storage_pwd: str = "",
        extension: str = "",
        domain: str = "storage.local",
        workspace: Path | None = None,
    ) -> None:
        """Синхронизировать хранилище в git-репозиторий workdir (src-layout)."""
        run = new_stats_run("gitsync", project_name, storage)
        run_start = monotonic()
        src_dir = workdir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        workspace = workspace or (self.cfg.temp_root / "gitsync-ws")
        temp_dir = self.cfg.temp_root / "gitsync-temp"
        env = self._env(project_name, workspace)
        v8 = self.cfg.effective_v8_version() or "8.3"
        global_opts = ["--v8version", v8, "--tempdir", str(temp_dir), "--domain-email", domain]

        if not (src_dir / "VERSION").is_file():
            info(f"gitsync: инициализация workdir {workdir}")
            # edtExport мешает init (требует project-name, регистрируемый
            # только для sync) — отключаем на время init
            self._plugins("disable", env)
            try:
                self._run([*global_opts, "init", "-u", storage_user, str(storage), str(workdir)], env)
            finally:
                self._plugins("enable", env)

        self._ensure_git_repo(workdir)

        args = [*global_opts, "sync", "-u", storage_user]
        if storage_pwd:
            args += ["-p", storage_pwd]
        if extension:
            args += ["-e", extension]
        args += [str(storage), str(workdir)]
        info(f"gitsync: sync {storage} -> {workdir} (проект {project_name})")
        markers, _ = self._run_logged(args, env)

        # длительность версии = интервал до маркера следующей версии
        t_end = monotonic()
        for index, (number, ts) in enumerate(markers):
            nxt = markers[index + 1][1] if index + 1 < len(markers) else t_end
            run["versions"].append(
                {"version": number, "total_sec": round(nxt - ts, 2)}
            )
        run["duration_sec"] = round(t_end - run_start, 2)
        # статистика общая на worktree (уровень выше каталога проекта)
        append_stats(workdir.parent / STATS_FILE, run)
        if run["versions"]:
            slowest = max(run["versions"], key=lambda s: s["total_sec"])
            info(
                f"stats: {len(run['versions'])} versions in {run['duration_sec']}s "
                f"(slowest: v{slowest['version']} = {slowest['total_sec']}s) "
                f"-> {workdir.parent / STATS_FILE}"
            )
