import os
from pathlib import Path


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value.strip() if value.strip() else default


def env_flag(name: str, default: str = "0") -> bool:
    return env(name, default) in ("1", "true", "yes", "on")


def secret(name: str, file_name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    path = os.environ.get(file_name, "")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


class Config:
    def __init__(self) -> None:
        self.temp_root = Path(env("CONVERT_TEMP_ROOT", "/tmp/onec-convert"))
        self.edt_ws_root = Path(env("CONVERT_EDT_WS_ROOT", str(self.temp_root.parent / "edt-ws")))
        self.clean_dst = env_flag("CONVERT_CLEAN_DST") or env_flag("V8_CONF_CLEAN_DST")
        self.keep_temp = env_flag("CONVERT_KEEP_TEMP")
        self.edt_xmx = env("CONVERT_EDT_XMX", "2g")
        self.edt_timeout = env("CONVERT_EDT_TIMEOUT", "1800")
        self.v8_version = env("V8_VERSION")

        self.ib_user = env("V8_IB_USER")
        self.ib_pwd = secret("V8_IB_PWD", "V8_IB_PWD_FILE")

        self.db_srv_dbms = env("V8_DB_SRV_DBMS", "PostgreSQL")
        self.db_srv_usr = env("V8_DB_SRV_USR")
        self.db_srv_pwd = secret("V8_DB_SRV_PWD", "V8_DB_SRV_PWD_FILE")

    def effective_v8_version(self) -> str:
        if self.v8_version:
            return self.v8_version
        try:
            current = Path("/opt/1cv8/current")
            resolved = current.resolve()
            name = resolved.name
            parts = name.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return name
        except OSError:
            pass
        return ""
