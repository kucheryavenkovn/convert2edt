import re
from dataclasses import dataclass
from pathlib import Path

CF = "cf"
FILE_IB = "file_ib"
SERVER_IB = "server_ib"
XML = "xml"
EDT = "edt"

KIND_TITLES = {
    CF: "Configuration file (CF)",
    FILE_IB: "File infobase",
    SERVER_IB: "Server infobase",
    XML: "1C:Designer XML files",
    EDT: "1C:EDT project",
}


@dataclass
class Source:
    kind: str
    path: str = ""
    db_server: str = ""
    db_name: str = ""

    def describe(self) -> str:
        title = KIND_TITLES.get(self.kind, self.kind)
        if self.kind == SERVER_IB:
            return f"{title} ({self.db_server}\\{self.db_name})"
        return f"{title} ({self.path})"


def detect_source(raw: str) -> Source:
    value = raw.strip()
    low = value.lower()

    if low.endswith(".cf"):
        return Source(CF, path=value)

    if low.startswith("/f") and len(value) > 2:
        return Source(FILE_IB, path=value[2:])

    if low.startswith("/s") and len(value) > 2:
        match = re.match(r"^([^\\/]+)[\\/](.+)$", value[2:])
        if not match:
            raise ValueError(
                f"Invalid server infobase reference: {value} (expected /S<server>\\<ref>)"
            )
        return Source(SERVER_IB, db_server=match.group(1), db_name=match.group(2))

    path = Path(value)
    if (path / "1cv8.1cd").is_file():
        return Source(FILE_IB, path=str(path))

    if (path / "Configuration.xml").is_file():
        return Source(XML, path=str(path))

    if (path / "DT-INF").is_dir() or (
        (path / ".project").is_file() and (path / "src").is_dir()
    ):
        return Source(EDT, path=str(path))

    raise ValueError(
        f'Cannot detect type of "{value}": expected 1C configuration file (*.cf), '
        "infobase (/F<path>, /S<server>\\<ref> or directory with 1cv8.1cd), "
        "1C:Designer XML files (directory with Configuration.xml) "
        "or 1C:EDT project (directory with DT-INF or .project + src)"
    )
