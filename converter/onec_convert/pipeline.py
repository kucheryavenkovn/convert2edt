import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .detect import CF, EDT, FILE_IB, SERVER_IB, Source, detect_source
from .edtcli import EdtCli
from .env import Config
from .ibcmd import Ibcmd
from .proc import info, run_tool


VCS_DIRS = frozenset({".git"})

SYNC_COMMITTER_NAME = "1c-convert storage-sync"
SYNC_COMMITTER_EMAIL = "1c-convert@storage.local"
STATE_FILE = ".storage-sync.json"


def load_authors(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    authors: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid authors mapping line: {line}")
        key, value = line.split("=", 1)
        authors[key.strip()] = value.strip()
    return authors


def resolve_author(version, users: dict[str, str], authors: dict[str, str], domain: str) -> str:
    name = users.get(version.userid, "") or f"user-{version.userid[:8]}"
    if name in authors:
        return authors[name]
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", name).strip("-")
    if not re.search(r"[0-9A-Za-z]", slug):
        slug = version.userid.replace("-", "")[:12]
    if not slug:
        slug = "unknown"
    return f"{name} <{slug}@{domain}>"


def read_state(path: Path) -> dict:
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"projects": {}}
        if isinstance(state, dict) and "projects" not in state:
            last = state.get("last_version", 0)
            return {"projects": {"configuration": last}}
        if isinstance(state, dict):
            state.setdefault("projects", {})
            return state
    return {"projects": {}}


def write_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_git(worktree: Path, *args: str, env_extra: dict | None = None) -> str:
    env = {**os.environ, **(env_extra or {})}
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {(result.stderr or result.stdout or '').strip()}"
        )
    return (result.stdout or "").strip()


def ensure_git_repo(worktree: Path) -> None:
    worktree.mkdir(parents=True, exist_ok=True)
    if not (worktree / ".git").exists():
        run_git(worktree, "init", "-q")
    gitignore = worktree / ".gitignore"
    if gitignore.is_file():
        content = gitignore.read_text(encoding="utf-8")
    else:
        content = ""
    if STATE_FILE not in content.splitlines():
        lines = [line for line in content.splitlines() if line.strip()]
        lines.append(STATE_FILE)
        gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit_version(worktree: Path, project_name: str, version, author: str) -> bool:
    run_git(worktree, "add", "-A", "--", project_name, ".gitignore")
    staged = run_git(worktree, "diff", "--cached", "--name-only")
    if not staged:
        info(f"version {version.number}: no changes, commit skipped")
        return False
    message = f"Версия {version.number}: {(version.comment or '').strip() or 'без комментария'}"
    dates = {"GIT_AUTHOR_DATE": version.date, "GIT_COMMITTER_DATE": version.date}
    run_git(
        worktree,
        "-c",
        f"user.name={SYNC_COMMITTER_NAME}",
        "-c",
        f"user.email={SYNC_COMMITTER_EMAIL}",
        "commit",
        "-q",
        f"--author={author}",
        "-m",
        message,
        env_extra=dates,
    )
    info(f"version {version.number}: committed as {author}")
    return True


class TempArea:
    def __init__(self, root: Path, name: str) -> None:
        self.root = root / name
        self.ibcmd_data = self.root / "ibcmd_data"

    def reset(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ibcmd_data.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class Pipeline:
    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.ibcmd = Ibcmd(self.cfg)
        self.edt = EdtCli(self.cfg)
        self._temp: TempArea | None = None
        self._workspaces: list[Path] = []

    def temp(self, name: str) -> TempArea:
        area = TempArea(self.cfg.temp_root, name)
        area.reset()
        self._temp = area
        return area

    def workspace(self, project: Path) -> Path:
        ws = self.cfg.edt_ws_root / f"ws-{uuid4().hex[:12]}"
        ws.mkdir(parents=True, exist_ok=True)
        self._workspaces.append(ws)
        return ws

    def finish_temp(self, failed: bool = False) -> None:
        if self._temp is not None:
            if failed or self.cfg.keep_temp:
                info(f"temporary files kept for inspection: {self._temp.root}")
            else:
                self._temp.cleanup()
            self._temp = None
        for ws in self._workspaces:
            if failed or self.cfg.keep_temp:
                info(f"EDT workspace kept for inspection: {ws}")
            else:
                shutil.rmtree(ws, ignore_errors=True)
        self._workspaces = []

    def clean_dst(self, path: Path) -> None:
        if self.cfg.clean_dst and path.exists():
            info(f"cleaning destination: {path}")
            shutil.rmtree(path, ignore_errors=True)

    def clean_edt_project_dst(self, project: Path) -> None:
        if not project.exists():
            return
        for item in project.iterdir():
            if item.name in VCS_DIRS:
                continue
            if item.is_symlink() or item.is_file():
                item.unlink()
            else:
                shutil.rmtree(item)
        info(
            f"EDT project destination cleared for full re-import "
            f"(edtExport approach, VCS dirs preserved): {project}"
        )

    def file_ib(self, path: Path) -> Source:
        return Source(FILE_IB, path=str(path))

    def assert_xml_dir(self, xml_dir: Path) -> None:
        if not (xml_dir / "Configuration.xml").is_file():
            raise RuntimeError(
                f"Configuration.xml was not found in {xml_dir} — export result is invalid"
            )

    def assert_edt_project(self, project: Path) -> None:
        for marker in (".project", "src"):
            if not (project / marker).exists():
                raise RuntimeError(
                    f"EDT project marker '{marker}' was not found in {project} — "
                    "import result is invalid"
                )
        if not (project / "src" / "Configuration" / "Configuration.mdo").is_file():
            raise RuntimeError(
                f"src/Configuration/Configuration.mdo was not found in {project} — "
                "import result is invalid"
            )

    def assert_file(self, path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"result file was not created or is empty: {path}")

    def edt_import_flow(self, xml: Path, dst_project: Path) -> None:
        ws = self.workspace(dst_project)
        dst_project.mkdir(parents=True, exist_ok=True)
        self.clean_edt_project_dst(dst_project)
        version = self.cfg.effective_v8_version()
        self.edt.import_project(ws, xml, dst_project, version=version)
        self.assert_edt_project(dst_project)
        self.edt.clean_up_source(ws, dst_project)
        self.assert_edt_project(dst_project)

    def need_sync(self, dst_xml: Path, mode: str) -> bool:
        if mode == "force":
            return True
        if mode == "off":
            return False
        return (dst_xml / "Configuration.xml").is_file() and (
            dst_xml / "ConfigDumpInfo.xml"
        ).is_file()

    def require_ib(self, source: Source) -> Source:
        if source.kind not in (FILE_IB, SERVER_IB):
            raise ValueError(f"infobase expected, got: {source.describe()}")
        return source

    def require_kind(self, source: Source, *kinds: str) -> Source:
        if source.kind not in kinds:
            expected = " or ".join(kinds)
            raise ValueError(
                f"{expected} source expected, got: {source.describe()}"
            )
        return source

    def run(self, name: str, steps) -> None:
        saved_temp = self._temp
        saved_workspaces = self._workspaces
        self._temp = None
        self._workspaces = []
        failed = False
        try:
            steps()
        except Exception:
            failed = True
            raise
        finally:
            self.finish_temp(failed=failed)
            self._temp = saved_temp
            self._workspaces = saved_workspaces

    def cf_to_xml(self, src_cf: Path, dst_xml: Path, sync: str = "auto") -> None:
        def steps() -> None:
            source = self.require_kind(detect_source(str(src_cf)), CF)
            info(f"source: {source.describe()}")
            temp = self.temp("cf-to-xml")
            ib = temp.root / "tmp_db"
            info(f'creating temporary infobase from "{src_cf}"...')
            self.ibcmd.create_from_cf(temp.ibcmd_data, ib, src_cf)
            dst_xml.mkdir(parents=True, exist_ok=True)
            use_sync = self.need_sync(dst_xml, sync)
            if use_sync:
                info("using incremental export (--sync)")
            self.ibcmd.config_export(
                temp.ibcmd_data, self.file_ib(ib), dst_xml, sync=use_sync
            )
            self.assert_xml_dir(dst_xml)
            info(f"result: {dst_xml}")

        self.run("cf-to-xml", steps)

    def xml_to_cf(self, src_xml: Path, dst_cf: Path) -> None:
        def steps() -> None:
            self.require_kind(detect_source(str(src_xml)), "xml")
            temp = self.temp("xml-to-cf")
            ib = temp.root / "tmp_db"
            info(f'creating temporary infobase from XML "{src_xml}"...')
            self.ibcmd.create_from_xml(temp.ibcmd_data, ib, src_xml)
            dst_cf.parent.mkdir(parents=True, exist_ok=True)
            self.ibcmd.config_save(temp.ibcmd_data, self.file_ib(ib), dst_cf)
            self.assert_file(dst_cf)
            info(f"result: {dst_cf}")

        self.run("xml-to-cf", steps)

    def xml_to_edt(self, src_xml: Path, dst_project: Path) -> None:
        def steps() -> None:
            self.require_kind(detect_source(str(src_xml)), "xml")
            self.edt_import_flow(src_xml, dst_project)
            info(f"result: {dst_project}")

        self.run("xml-to-edt", steps)

    def edt_to_xml(self, src_project: Path, dst_xml: Path) -> None:
        def steps() -> None:
            self.require_kind(detect_source(str(src_project)), EDT)
            ws = self.workspace(src_project)
            self.clean_dst(dst_xml)
            dst_xml.mkdir(parents=True, exist_ok=True)
            self.edt.export_project(ws, src_project, dst_xml)
            self.assert_xml_dir(dst_xml)
            info(f"result: {dst_xml}")

        self.run("edt-to-xml", steps)

    def cf_to_edt(self, src_cf: Path, dst_project: Path) -> None:
        def steps() -> None:
            source = self.require_kind(detect_source(str(src_cf)), CF)
            info(f"source: {source.describe()}")
            temp = self.temp("cf-to-edt")
            ib = temp.root / "tmp_db"
            xml = temp.root / "tmp_xml"
            info(f'creating temporary infobase from "{src_cf}"...')
            self.ibcmd.create_from_cf(temp.ibcmd_data, ib, src_cf)
            info("exporting configuration to 1C:Designer XML...")
            self.ibcmd.config_export(temp.ibcmd_data, self.file_ib(ib), xml)
            self.assert_xml_dir(xml)
            self.edt_import_flow(xml, dst_project)
            info(f"result: {dst_project}")

        self.run("cf-to-edt", steps)

    def edt_to_cf(self, src_project: Path, dst_cf: Path) -> None:
        def steps() -> None:
            self.require_kind(detect_source(str(src_project)), EDT)
            temp = self.temp("edt-to-cf")
            ws = self.workspace(src_project)
            xml = temp.root / "tmp_xml"
            info("exporting 1C:EDT project to 1C:Designer XML...")
            self.edt.export_project(ws, src_project, xml)
            self.assert_xml_dir(xml)
            ib = temp.root / "tmp_db"
            info(f'creating temporary infobase from XML "{xml}"...')
            self.ibcmd.create_from_xml(temp.ibcmd_data, ib, xml)
            dst_cf.parent.mkdir(parents=True, exist_ok=True)
            self.ibcmd.config_save(temp.ibcmd_data, self.file_ib(ib), dst_cf)
            self.assert_file(dst_cf)
            info(f"result: {dst_cf}")

        self.run("edt-to-cf", steps)

    def ib_to_xml(self, src_ib: str, dst_xml: Path, sync: str = "auto") -> None:
        def steps() -> None:
            source = self.require_ib(detect_source(src_ib))
            info(f"source: {source.describe()}")
            temp = self.temp("ib-to-xml")
            dst_xml.mkdir(parents=True, exist_ok=True)
            use_sync = self.need_sync(dst_xml, sync)
            if use_sync:
                info("using incremental export (--sync)")
            self.ibcmd.config_export(
                temp.ibcmd_data, source, dst_xml, sync=use_sync
            )
            self.assert_xml_dir(dst_xml)
            info(f"result: {dst_xml}")

        self.run("ib-to-xml", steps)

    def ib_to_edt(self, src_ib: str, dst_project: Path) -> None:
        def steps() -> None:
            source = self.require_ib(detect_source(src_ib))
            info(f"source: {source.describe()}")
            temp = self.temp("ib-to-edt")
            xml = temp.root / "tmp_xml"
            info("exporting configuration to 1C:Designer XML...")
            self.ibcmd.config_export(temp.ibcmd_data, source, xml)
            self.assert_xml_dir(xml)
            self.edt_import_flow(xml, dst_project)
            info(f"result: {dst_project}")

        self.run("ib-to-edt", steps)

    def storage_prepare(self, storage: str, name: str):
        from .tool1cd import Tool1CD, locate_storage_db, prepare_local_copy

        db = locate_storage_db(storage)
        temp = self.temp(name)
        local_db = prepare_local_copy(db, temp.root)
        tool = Tool1CD(self.cfg)
        versions = tool.versions(local_db, temp.root / "tables")
        users = tool.users(local_db, temp.root / "tables")
        if not versions:
            raise RuntimeError(f"no versions found in storage {storage}")
        info(f"storage: {db} ({len(versions)} versions, {len(users)} users)")
        return temp, tool, local_db, versions, users

    def storage_to_cf(self, storage: str, dst_cf: Path, version: int = 0) -> None:
        def steps() -> None:
            temp, tool, local_db, versions, _ = self.storage_prepare(storage, "storage-to-cf")
            number = versions[-1].number if version == 0 else version
            info(f"dumping configuration of version {number}...")
            tool.dump_config(local_db, number, dst_cf)

        self.run("storage-to-cf", steps)

    def storage_to_xml(self, storage: str, dst_xml: Path, version: int = 0) -> None:
        def steps() -> None:
            temp, tool, local_db, versions, _ = self.storage_prepare(storage, "storage-to-xml")
            number = versions[-1].number if version == 0 else version
            info(f"dumping configuration of version {number}...")
            cf = temp.root / f"ver-{number}.cf"
            tool.dump_config(local_db, number, cf)
            self.cf_to_xml(cf, dst_xml)

        self.run("storage-to-xml", steps)

    def storage_to_edt(self, storage: str, dst_project: Path, version: int = 0) -> None:
        def steps() -> None:
            temp, tool, local_db, versions, _ = self.storage_prepare(storage, "storage-to-edt")
            number = versions[-1].number if version == 0 else version
            info(f"dumping configuration of version {number}...")
            cf = temp.root / f"ver-{number}.cf"
            tool.dump_config(local_db, number, cf)
            self.cf_to_edt(cf, dst_project)

        self.run("storage-to-edt", steps)

    def storage_sync(
        self,
        storage: str,
        worktree: Path,
        project_name: str = "configuration",
        version_from: int = 0,
        version_to: int = 0,
        authors_file: Path | None = None,
        domain: str = "storage.local",
        extension: str = "",
    ) -> None:
        def steps() -> None:
            temp, tool, local_db, versions, users = self.storage_prepare(
                storage, "storage-sync"
            )
            authors = load_authors(authors_file)
            state_file = worktree / STATE_FILE
            state = read_state(state_file)
            last_done = state["projects"].get(project_name, 0)
            start = version_from or (last_done + 1)
            end = version_to or versions[-1].number
            todo = [v for v in versions if start <= v.number <= end]
            info(
                f"syncing {project_name}: versions {start}..{end} "
                f"({len(todo)} to do, last done {last_done})"
            )
            project_dir = worktree / project_name
            ensure_git_repo(worktree)
            for v in todo:
                info(f"--- version {v.number}: {v.comment or '(no comment)'}")
                cf = temp.root / f"ver-{v.number}.cf"
                tool.dump_config(local_db, v.number, cf)
                if extension:
                    xml = self.extension_to_xml(cf, extension, temp, None, v.number)
                    self.edt_import_flow(xml, project_dir)
                else:
                    self.cf_to_edt(cf, project_dir)
                author = resolve_author(v, users, authors, domain)
                commit_version(worktree, project_name, v, author)
                state["projects"][project_name] = v.number
                write_state(state_file, state)
            info(f"sync done: {todo[-1].number if todo else last_done} -> {worktree}")

        self.run("storage-sync", steps)

    def extension_to_xml(
        self, cfe_file: Path, extension: str, temp: TempArea, base_cf: Path | None, version: int
    ) -> Path:
        del base_cf
        ib = temp.root / f"ext_ib_{version}"
        data = temp.root / f"ext_data_{version}"
        data.mkdir(parents=True, exist_ok=True)
        info(
            f"loading extension dump into temporary infobase (as configuration; "
            "ibcmd --extension load drops storage-dumped objects)"
        )
        self.ibcmd.create_from_cf(data, ib, cfe_file)
        xml = temp.root / f"ext_xml_{version}"
        info("exporting extension to 1C:Designer XML...")
        self.ibcmd.config_export(data, self.file_ib(ib), xml)
        self.assert_xml_dir(xml)
        return xml


def platform_version() -> str:
    try:
        return Path("/opt/1cv8/current").resolve().name
    except OSError:
        return "unknown"


def edt_version() -> str:
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="edt-ver-") as ws:
        result = subprocess.run(
            ["1cedtcli", "-data", ws, "-timeout", "300", "-command", "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        text = (result.stdout or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else "unknown"
