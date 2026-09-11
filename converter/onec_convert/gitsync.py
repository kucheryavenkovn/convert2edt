"""Движок gitsync: хранилище 1С -> git через oscript-library/gitsync.

Альтернатива нативному конвейеру (ctool1cd + ibcmd + 1cedtcli):
  * версии хранилища читает gitsync (конфигуратор 1С или плагин tool1CD —
    см. storage_backend); хранилища РАСШИРЕНИЙ поддерживаются штатным
    конфигуратором через `-Extension` (в т.ч. в `gitsync init -e`!);
  * XML -> EDT делает плагин gitsync `edtExport` (>= 2.0.1, через 1cedtcli);
  * git-историю (коммиты, авторы из AUTHORS, даты) формирует сам gitsync.

Селективные бэкенды (конфиг [gitsync]):
  * storage_backend = configurator | ctool1cd — чтение хранилища
    (плагин tool1CD: только Windows — плагин тащит Windows-бинарники и в
    Linux требует wine; расширения плагин не поддерживает);
  * xml_backend = configurator | ibcmd — выгрузка конфигурации в XML
    (плагин use-ibcmd, нативный ibcmd из образа/системы).

Особенности (проверено локально и в Docker, см. scripts/local/run-gitsync.ps1):
  * workdir проекта ДОЛЖЕН с первого запуска содержать каталог `src`
    (issue oscript-library/gitsync-plugins#53): gitsync кладёт исходники в
    WORKDIR/src, если тот существует; EDT-проект живёт в src стабильно;
  * `gitsync init` конфликтует с edtExport (project-name не зарегистрирован
    для init) — на время init плагин отключается и включается обратно;
  * хранилище расширения: init/sync обязаны получать -e (иначе платформа
    отказывает «Соединение основной конфигурации с хранилищем расширений
    конфигураций невозможно»); инкрементальный -update-дамп расширений у
    платформы не работает («Объект метаданных ... не существует в
    конфигурации») — для расширений плагин increment выключается;
  * OneScript 1.9.4: задание OSCRIPT_CONFIG=lib.additional выключает поиск
    библиотек в <gitsync>/oscript_modules — run-gitsync.ps1 зеркалит нужные
    пакеты (json, gitrunner, edtfind и др.) в tools/oscript/oscript_modules;
    здесь каталог просто подхватывается, если существует.
"""

import json
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

STORAGE_BACKENDS = ("configurator", "ctool1cd")
XML_BACKENDS = ("configurator", "ibcmd")

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


# строки подключения к серверу хранилища (crs) и http-публикациям
REMOTE_STORAGE_PREFIXES = ("tcp://", "http://", "https://", "tcp:", "http:")


def is_remote_storage(storage: str) -> bool:
    return (storage or "").strip().lower().startswith(REMOTE_STORAGE_PREFIXES)


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

    def _env(self, project_name: str, workspace: Path, extension: str = "") -> dict:
        env = dict(os.environ)
        env["GITSYNC_PROJECT_NAME"] = project_name
        env["GITSYNC_WORKSPACE_LOCATION"] = str(workspace)
        # GITSYNC_EXTENSION должна действовать на ВСЕ команды gitsync
        # (init тоже: привязка хранилища расширения идёт с -Extension,
        # без него платформа отказывает «Соединение основной конфигурации
        # с хранилищем расширений конфигураций невозможно»)
        if extension:
            env["GITSYNC_EXTENSION"] = extension
        else:
            env.pop("GITSYNC_EXTENSION", None)
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

    def _plugins_catalog(self) -> Path:
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
            return base / "gitsync" / "plugins"
        return Path.home() / ".local" / "share" / "gitsync" / "plugins"

    def _set_plugin(self, name: str, enabled: bool) -> None:
        """Включить/выключить плагин gitsync правкой plugins.json.

        Команды `gitsync plugins enable/disable` в связке oscript 1.9.4 +
        gitsync 3.8.0 падают с TypeInitializationException Newtonsoft.Json,
        а сам файл плагины пишут тривиально — правим напрямую.
        """
        catalog = self._plugins_catalog()
        path = catalog / "plugins.json"
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
        data[name] = enabled
        catalog.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _set_edt_export(self, enabled: bool) -> None:
        self._set_plugin("edtExport", enabled)

    def _ensure_git_repo(self, workdir: Path) -> None:
        # gitsync init может не создать .git; worktree внутри другого
        # репозитория тогда подхватывает чужой .gitignore — страхуемся
        if not (workdir / ".git").exists():
            run_tool(["git", "-C", str(workdir), "init", "-q"])

    def _prepare_storage(self, storage: str, project_name: str) -> Path:
        """Локальная записываемая копия хранилища.

        Работа с хранилищем (локи, 1cv8dtmp) требует записи в его каталог,
        а источник может быть смонтирован read-only — поэтому, как и в
        tool1cd-движке, всегда работаем с копией в cache/tmp.
        """
        from .tool1cd import locate_storage_db, prepare_local_copy

        db = locate_storage_db(str(storage))
        local_db = prepare_local_copy(
            db, self.cfg.temp_root / "gitsync-storage" / project_name
        )
        return local_db.parent

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
        storage_backend: str = "configurator",
        xml_backend: str = "configurator",
        ib_connection: str = "",
        ib_user: str = "",
        ib_pwd: str = "",
        ibcmd_dbms: str = "",
        ibcmd_db_server: str = "",
        ibcmd_db_name: str = "",
        ibcmd_db_user: str = "",
        ibcmd_db_pwd: str = "",
    ) -> None:
        """Синхронизировать хранилище в git-репозиторий workdir (src-layout).

        storage_backend: configurator (штатный, поддерживает и хранилища
        расширений через -Extension; также УДАЛЁННЫЕ хранилища tcp://) |
        ctool1cd (плагин tool1CD; только Windows, без лицензии на чтение
        хранилища; расширения и tcp:// НЕ умеет).
        xml_backend: configurator (DESIGNER DumpConfigToFiles) | ibcmd
        (плагин use-ibcmd, нативный ibcmd).
        storage: файловый каталог/файл 1cv8ddb.1CD ЛИБО строка подключения
        к серверу хранилища (crs): tcp://host:port/имя_репозитория.
        ib_connection: ИБ для выгрузки (/S<server>\\<ref> или /F<путь>);
        пусто = временная файловая ИБ (как раньше).
        ibcmd_*: параметры СУБД для плагина use-ibcmd при серверной ИБ.
        """
        if storage_backend not in STORAGE_BACKENDS:
            raise GitSyncError(
                f"storage_backend должен быть {' или '.join(STORAGE_BACKENDS)}, "
                f"получено: {storage_backend!r}"
            )
        if xml_backend not in XML_BACKENDS:
            raise GitSyncError(
                f"xml_backend должен быть {' или '.join(XML_BACKENDS)}, "
                f"получено: {xml_backend!r}"
            )
        remote_storage = is_remote_storage(storage)
        if remote_storage:
            info(f"gitsync: удалённое хранилище (сервер хранилища): {storage}")
        if storage_backend == "ctool1cd":
            if remote_storage:
                raise GitSyncError(
                    "плагин tool1CD работает только с файлом 1cv8ddb.1CD; "
                    "для удалённых хранилищ (tcp://) используйте "
                    "storage_backend = configurator"
                )
            if extension:
                raise GitSyncError(
                    "плагин tool1CD не поддерживает хранилища расширений; "
                    "для расширений используйте storage_backend = configurator "
                    "или движок tool1cd"
                )
            if os.name != "nt":
                raise GitSyncError(
                    "плагин tool1CD выполняет виндовые бинарники (в Linux "
                    "требуется wine — не используется); в Docker доступен "
                    "только storage_backend = configurator"
                )

        run = new_stats_run("gitsync", project_name, storage)
        run_start = monotonic()
        if remote_storage:
            # сервер хранилища (crs): строка подключения передаётся как есть
            storage_path = storage.strip()
        else:
            storage_path = self._prepare_storage(storage, project_name)
            info(f"gitsync: работаю с копией хранилища: {storage_path}")
        info(
            f"gitsync: бэкенды — чтение хранилища: {storage_backend}, "
            f"выгрузка XML: {xml_backend}"
        )
        src_dir = workdir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        workspace = workspace or (self.cfg.temp_root / "gitsync-ws")
        temp_dir = self.cfg.temp_root / "gitsync-temp"
        env = self._env(project_name, workspace, extension)
        if xml_backend == "ibcmd":
            # плагин use-ibcmd требует рабочий каталог --data для ibcmd
            ibcmd_data = temp_dir / "ibcmd-data"
            ibcmd_data.mkdir(parents=True, exist_ok=True)
            env["GITSYNC_IBCMD_DATA"] = str(ibcmd_data)
            # параметры СУБД для клиент-серверной ИБ
            if ibcmd_dbms:
                env["GITSYNC_IBCMD_DBMS"] = ibcmd_dbms
            if ibcmd_db_server:
                env["GITSYNC_IBCMD_DB_SERVER"] = ibcmd_db_server
            if ibcmd_db_name:
                env["GITSYNC_IBCMD_DB_NAME"] = ibcmd_db_name
            if ibcmd_db_user:
                env["GITSYNC_IBCMD_DB_USER"] = ibcmd_db_user
            if ibcmd_db_pwd:
                env["GITSYNC_IBCMD_DB_PWD"] = ibcmd_db_pwd
        v8 = self.cfg.effective_v8_version() or "8.3"
        global_opts = ["--v8version", v8, "--tempdir", str(temp_dir), "--domain-email", domain]
        if ib_connection:
            # клиент-серверная (или иная внешняя) ИБ вместо временной файловой
            info(f"gitsync: ИБ для выгрузки: {ib_connection}")
            global_opts += ["-C", ib_connection]
            if ib_user:
                global_opts += ["-U", ib_user]
            if ib_pwd:
                global_opts += ["-P", ib_pwd]

        # детерминированное состояние плагинов на прогон:
        #  * tool1CD/use-ibcmd — по выбранным бэкендам;
        #  * increment — выключен для хранилищ расширений (инкрементальный
        #    -update-дамп расширений не работает у платформы)
        self._set_plugin("tool1CD", storage_backend == "ctool1cd")
        self._set_plugin("use-ibcmd", xml_backend == "ibcmd")
        self._set_plugin("increment", not extension)

        if not (src_dir / "VERSION").is_file():
            info(f"gitsync: инициализация workdir {workdir}")
            # edtExport мешает init (требует project-name, регистрируемый
            # только для sync) — отключаем на время init
            self._set_edt_export(False)
            try:
                init_args = [*global_opts, "init", "-u", storage_user]
                if extension:
                    # init тоже должен знать, что хранилище — расширение
                    init_args += ["-e", extension]
                init_args += [str(storage_path), str(workdir)]
                self._run(init_args, env)
            finally:
                self._set_edt_export(True)

        self._ensure_git_repo(workdir)

        args = [*global_opts, "sync", "-u", storage_user]
        if storage_pwd:
            args += ["-p", storage_pwd]
        if extension:
            args += ["-e", extension]
        args += [str(storage_path), str(workdir)]
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
