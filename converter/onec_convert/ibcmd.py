from pathlib import Path

from .detect import FILE_IB, Source
from .env import Config
from .proc import run_tool


class Ibcmd:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _conn_args(self, ib: Source) -> list[str]:
        args: list[str] = []
        if ib.kind == "server_ib":
            args.append(f"--dbms={self.cfg.db_srv_dbms}")
            args.append(f"--db-server={ib.db_server}")
            args.append(f"--db-name={ib.db_name}")
            if self.cfg.db_srv_usr:
                args.append(f"--db-user={self.cfg.db_srv_usr}")
            if self.cfg.db_srv_pwd:
                args.extend(["--db-pwd", self.cfg.db_srv_pwd])
        else:
            args.append(f"--db-path={ib.path}")
        if self.cfg.ib_user:
            args.append(f"--user={self.cfg.ib_user}")
        if self.cfg.ib_pwd:
            args.extend(["--password", self.cfg.ib_pwd])
        return args

    def _file_ib(self, path: Path) -> Source:
        return Source(FILE_IB, path=str(path))

    def create_from_cf(self, data_dir: Path, ib_path: Path, cf_file: Path) -> None:
        run_tool(
            [
                "ibcmd",
                "infobase",
                "create",
                f"--data={data_dir}",
                f"--db-path={ib_path}",
                "--create-database",
                f"--load={cf_file}",
            ]
        )

    def create_from_xml(self, data_dir: Path, ib_path: Path, xml_dir: Path) -> None:
        run_tool(
            [
                "ibcmd",
                "infobase",
                "create",
                f"--data={data_dir}",
                f"--db-path={ib_path}",
                "--create-database",
                f"--import={xml_dir}",
            ]
        )

    def create_empty(self, data_dir: Path, ib_path: Path) -> None:
        run_tool(
            [
                "ibcmd",
                "infobase",
                "create",
                f"--data={data_dir}",
                f"--db-path={ib_path}",
                "--create-database",
            ]
        )

    def config_load(
        self, data_dir: Path, ib: Source, cf_file: Path, extension: str = ""
    ) -> None:
        flags = ["--force"]
        if extension:
            flags.append(f"--extension={extension}")
        run_tool(
            [
                "ibcmd",
                "infobase",
                "config",
                "load",
                f"--data={data_dir}",
                *self._conn_args(ib),
                *flags,
                str(cf_file),
            ]
        )

    def config_export(
        self,
        data_dir: Path,
        ib: Source,
        xml_dir: Path,
        sync: bool = False,
        extension: str = "",
    ) -> None:
        flags = ["--force"]
        if sync:
            flags.append("--sync")
        if extension:
            flags.append(f"--extension={extension}")
        run_tool(
            [
                "ibcmd",
                "infobase",
                "config",
                "export",
                f"--data={data_dir}",
                *self._conn_args(ib),
                *flags,
                str(xml_dir),
            ]
        )

    def config_save(
        self, data_dir: Path, ib: Source, cf_file: Path, extension: str = ""
    ) -> None:
        flags = []
        if extension:
            flags.append(f"--extension={extension}")
        run_tool(
            [
                "ibcmd",
                "infobase",
                "config",
                "save",
                f"--data={data_dir}",
                *self._conn_args(ib),
                *flags,
                str(cf_file),
            ]
        )
