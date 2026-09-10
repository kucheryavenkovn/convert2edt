import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .env import Config
from .proc import info, mask_command

CONTROL_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class StorageVersion:
    number: int
    date: str
    userid: str
    comment: str

    def describe(self) -> str:
        comment = (self.comment or "").replace("\n", " ").strip()
        return f"#{self.number} {self.date} [{self.userid}] {comment}"


class Tool1CDError(RuntimeError):
    pass


def locate_storage_db(raw: str) -> Path:
    path = Path(raw)
    if path.is_file():
        return path
    if path.is_dir():
        for item in path.iterdir():
            if item.is_file() and item.name.lower() == "1cv8ddb.1cd":
                return item
    raise ValueError(
        f'Configuration storage was not found at "{raw}": '
        "expected 1cv8ddb.1CD file or directory containing it"
    )


def prepare_local_copy(db_file: Path, dest_root: Path) -> Path:
    storage_root = db_file.parent
    dest = dest_root / "storage"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(storage_root, dest)
    local_db = dest / db_file.name
    if not local_db.is_file():
        raise Tool1CDError(f"storage copy failed: {local_db} not found")
    return local_db


class Tool1CD:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _run(self, db: Path, args: list[str]) -> None:
        cmd = ["ctool1cd", str(db), "-ne", "-q", *args]
        print("+ " + mask_command(cmd), flush=True)
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
        output = result.stdout or ""
        tail = [line for line in output.splitlines() if line.strip()][-5:]
        for line in tail:
            info(f"tool1cd: {line}")
        if result.returncode != 0:
            raise Tool1CDError(
                f"ctool1cd exited with code {result.returncode}: {'; '.join(tail)}"
            )

    def dump_config(self, db: Path, version: int, out_cf: Path) -> None:
        out_cf.parent.mkdir(parents=True, exist_ok=True)
        self._run(db, ["-drc", str(version), str(out_cf)])
        if not out_cf.is_file() or out_cf.stat().st_size == 0:
            raise Tool1CDError(f"ctool1cd did not create {out_cf}")

    def _read_table(self, db: Path, out_dir: Path, table: str) -> ET.Element:
        out_dir.mkdir(parents=True, exist_ok=True)
        self._run(db, ["-ex", str(out_dir), table])
        xml_file = out_dir / f"{table}.xml"
        if not xml_file.is_file():
            raise Tool1CDError(f"ctool1cd did not export {xml_file}")
        raw = xml_file.read_bytes()
        raw = CONTROL_CHARS.sub(b"", raw)
        return ET.fromstring(raw)

    def versions(self, db: Path, work_dir: Path) -> list[StorageVersion]:
        root = self._read_table(db, work_dir, "VERSIONS")
        versions = []
        for record in root.findall(".//Record"):
            fields = {e.tag: (e.text or "") for e in record}
            try:
                number = int(fields.get("VERNUM", "0"))
            except ValueError:
                continue
            versions.append(
                StorageVersion(
                    number=number,
                    date=fields.get("VERDATE", ""),
                    userid=fields.get("USERID", ""),
                    comment=fields.get("COMMENT", ""),
                )
            )
        versions.sort(key=lambda v: v.number)
        return versions

    def users(self, db: Path, work_dir: Path) -> dict[str, str]:
        root = self._read_table(db, work_dir, "USERS")
        users = {}
        for record in root.findall(".//Record"):
            fields = {e.tag: (e.text or "") for e in record}
            userid = fields.get("USERID", "")
            name = fields.get("NAME", "") or userid
            users[userid] = name
        return users
