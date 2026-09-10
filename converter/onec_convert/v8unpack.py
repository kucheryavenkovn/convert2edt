import subprocess
from pathlib import Path

from .proc import mask_command


class V8UnpackError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    print("+ " + mask_command(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
    )
    if result.returncode != 0:
        tail = [line for line in (result.stdout or "").splitlines() if line.strip()][-5:]
        raise V8UnpackError(f"v8unpack exited with code {result.returncode}: {'; '.join(tail)}")


def unpack_to_sources(binary: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    _run(["v8unpack", "-P", str(binary), str(dest_dir)])


def build_from_sources(source_dir: Path, out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    _run(["v8unpack", "-B", str(source_dir), str(out_file)])
    if not out_file.is_file() or out_file.stat().st_size == 0:
        raise V8UnpackError(f"v8unpack did not create {out_file}")
