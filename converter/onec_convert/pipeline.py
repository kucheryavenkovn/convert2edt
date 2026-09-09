import hashlib
import shutil
from pathlib import Path

from .detect import CF, EDT, FILE_IB, SERVER_IB, Source, detect_source
from .edtcli import EdtCli
from .env import Config
from .ibcmd import Ibcmd
from .proc import info, run_tool


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

    def temp(self, name: str) -> TempArea:
        area = TempArea(self.cfg.temp_root, name)
        area.reset()
        self._temp = area
        return area

    def finish_temp(self, failed: bool = False) -> None:
        if self._temp is None:
            return
        if failed and not self.cfg.keep_temp:
            info(f"temporary files kept for inspection: {self._temp.root}")
            self._temp = None
            return
        if self.cfg.keep_temp:
            info(f"temporary files kept (CONVERT_KEEP_TEMP=1): {self._temp.root}")
            self._temp = None
            return
        self._temp.cleanup()
        self._temp = None

    def workspace(self, project: Path) -> Path:
        key = hashlib.sha1(str(project.resolve()).encode("utf-8")).hexdigest()[:12]
        ws = self.cfg.edt_ws_root / f"ws-{key}"
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def clean_dst(self, path: Path) -> None:
        if self.cfg.clean_dst and path.exists():
            info(f"cleaning destination: {path}")
            shutil.rmtree(path, ignore_errors=True)

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
        failed = False
        try:
            steps()
        except Exception:
            failed = True
            raise
        finally:
            self.finish_temp(failed=failed)

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
            ws = self.workspace(dst_project)
            self.clean_dst(dst_project)
            dst_project.mkdir(parents=True, exist_ok=True)
            version = self.cfg.effective_v8_version()
            self.edt.import_project(ws, src_xml, dst_project, version=version)
            self.assert_edt_project(dst_project)
            self.edt.clean_up_source(ws, dst_project)
            self.assert_edt_project(dst_project)
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
            ws = self.workspace(dst_project)
            self.clean_dst(dst_project)
            dst_project.mkdir(parents=True, exist_ok=True)
            version = self.cfg.effective_v8_version()
            self.edt.import_project(ws, xml, dst_project, version=version)
            self.assert_edt_project(dst_project)
            self.edt.clean_up_source(ws, dst_project)
            self.assert_edt_project(dst_project)
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
            ws = self.workspace(dst_project)
            self.clean_dst(dst_project)
            dst_project.mkdir(parents=True, exist_ok=True)
            version = self.cfg.effective_v8_version()
            self.edt.import_project(ws, xml, dst_project, version=version)
            self.assert_edt_project(dst_project)
            self.edt.clean_up_source(ws, dst_project)
            self.assert_edt_project(dst_project)
            info(f"result: {dst_project}")

        self.run("ib-to-edt", steps)


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
