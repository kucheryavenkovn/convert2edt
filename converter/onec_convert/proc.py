import re
import subprocess
import sys

SENSITIVE_FLAGS = {"--password", "--db-pwd", "--pwd", "--p"}

SENSITIVE_INLINE = re.compile(
    r"^(--password|--db-pwd|--pwd|--p)=(.*)$", re.IGNORECASE
)


def mask_command(cmd: list[str]) -> str:
    parts: list[str] = []
    hide_next = False
    for item in cmd:
        if hide_next:
            parts.append("******")
            hide_next = False
            continue
        inline = SENSITIVE_INLINE.match(item)
        if inline:
            parts.append(f"{inline.group(1)}=******")
            continue
        parts.append(item)
        if item.lower() in SENSITIVE_FLAGS:
            hide_next = True
    return " ".join(parts)


def run_tool(cmd: list[str]) -> subprocess.CompletedProcess:
    print("+ " + mask_command(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} exited with code {result.returncode}"
        )
    return result


def info(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)
