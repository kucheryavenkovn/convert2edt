import os
import re
import shlex
import subprocess
from pathlib import Path

from .env import Config
from .proc import mask_command, warn


def _edtcli_command() -> list[str]:
    override = os.environ.get("EDTCLI_TOOL", "").strip()
    if override:
        return shlex.split(override)
    return ["1cedtcli"]

ERROR_PATTERNS = [
    re.compile(r"\bERROR\b"),
    re.compile(r"\bFATAL\b"),
    re.compile(r"(?iu)\bошибк"),
    re.compile(r"(?iu)ошибок\s*:\s*[1-9]"),
    re.compile(r"Не удалось"),
    re.compile(r"Не найдено открытого проекта"),
    re.compile(r"java\.lang\."),
    re.compile(r"CoreException"),
]


class EdtCliError(RuntimeError):
    pass


class EdtCli:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _base(self, ws: Path) -> list[str]:
        return [
            *_edtcli_command(),
            "-data",
            str(ws),
            "-timeout",
            self.cfg.edt_timeout,
            "-vmargs",
            f"-Xmx{self.cfg.edt_xmx}",
        ]

    def import_project(
        self,
        ws: Path,
        xml_dir: Path,
        project: Path,
        version: str = "",
        base_project_name: str = "",
    ) -> None:
        cmd = [
            *self._base(ws),
            "-command",
            "import",
            "--project",
            str(project),
            "--configuration-files",
            str(xml_dir),
        ]
        if version:
            cmd.extend(["--version", version])
        if base_project_name:
            cmd.extend(["--base-project-name", base_project_name])
        self._run(cmd, ws)

    def import_existing(self, ws: Path, project: Path) -> None:
        self._run(
            [
                *self._base(ws),
                "-command",
                "import",
                "--project",
                str(project),
            ],
            ws,
        )

    def import_with_base(
        self,
        ws: Path,
        base_project_dir: Path,
        xml_dir: Path,
        project: Path,
        version: str = "",
        base_project_name: str = "",
    ) -> None:
        cmd = f'import --project "{project}" --configuration-files "{xml_dir}"'
        if version:
            cmd += f" --version {version}"
        if base_project_name:
            cmd += f' --base-project-name "{base_project_name}"'
        script = ws / "import.script"
        script.write_text(
            f'import --project "{base_project_dir}"\n' + cmd + "\n",
            encoding="utf-8",
        )
        try:
            self._run([*self._base(ws), "-file", str(script)], ws)
        finally:
            script.unlink(missing_ok=True)
    def export_project(self, ws: Path, project: Path, xml_dir: Path) -> None:
        self._run(
            [
                *self._base(ws),
                "-command",
                "export",
                "--project",
                str(project),
                "--configuration-files",
                str(xml_dir),
            ],
            ws,
        )

    def clean_up_source(self, ws: Path, project: Path) -> None:
        self._run(
            [
                *self._base(ws),
                "-command",
                "clean-up-source",
                "--project",
                str(project),
            ],
            ws,
        )

    def _run(self, cmd: list[str], ws: Path) -> None:
        print("+ " + mask_command(cmd), flush=True)
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
        output = result.stdout or ""
        if output:
            print(output, flush=True)

        for entry in self._scan_workspace_log(ws):
            warn(f"EDT workspace log entry: {entry}")

        console_problems = self._scan_problems(output)

        if result.returncode != 0:
            raise EdtCliError(
                f"1cedtcli exited with code {result.returncode}: {'; '.join(console_problems[:3])}"
            )
        if console_problems:
            raise EdtCliError(
                f"1cedtcli reported errors while exit code is 0: {'; '.join(console_problems[:3])}"
            )

    def _scan_problems(self, output: str) -> list[str]:
        found = []
        for line in output.splitlines():
            if any(p.search(line) for p in ERROR_PATTERNS):
                found.append(line.strip())
        return found

    def _scan_workspace_log(self, ws: Path) -> list[str]:
        log_file = ws / ".metadata" / ".log"
        if not log_file.is_file():
            return []
        problems = []
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for index, line in enumerate(lines):
            if line.startswith("!ENTRY") and re.search(r"\s4\s+\d+", line):
                context = "; ".join(
                    l.strip() for l in lines[index : index + 4] if l.strip()
                )
                problems.append(f".metadata/.log: {context}")
                if len(problems) >= 5:
                    break
        return problems
