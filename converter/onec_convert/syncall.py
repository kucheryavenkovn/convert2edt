import tomllib
from pathlib import Path

from .env import Config
from .pipeline import (
    SYNC_COMMITTER_EMAIL,
    SYNC_COMMITTER_NAME,
    Pipeline,
    ensure_git_repo,
    run_git,
)
from .proc import info


class SyncConfigError(RuntimeError):
    pass


def _load(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except FileNotFoundError as error:
        raise SyncConfigError(f"sync config not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise SyncConfigError(f"invalid TOML in {path}: {error}") from error


def commit_external(worktree: Path, paths: list[str], message: str) -> None:
    ensure_git_repo(worktree)
    run_git(worktree, "add", "-A", "--", *paths, ".gitignore")
    staged = run_git(worktree, "diff", "--cached", "--name-only")
    if not staged:
        info(f"no changes: {message}")
        return
    run_git(
        worktree,
        "-c",
        f"user.name={SYNC_COMMITTER_NAME}",
        "-c",
        f"user.email={SYNC_COMMITTER_EMAIL}",
        "commit",
        "-q",
        f"--author={SYNC_COMMITTER_NAME} <{SYNC_COMMITTER_EMAIL}>",
        "-m",
        message,
    )
    info(f"committed: {message}")


def sync_all(cfg: Config, config_path: Path) -> None:
    data = _load(config_path)
    worktree_conf = data.get("worktree") or {}
    worktree = Path(worktree_conf.get("path") or "")
    if not str(worktree):
        raise SyncConfigError("[worktree] path is required in sync config")

    authors_file = worktree_conf.get("authors_file") or None
    domain = worktree_conf.get("domain") or "storage.local"

    pipeline = Pipeline(cfg)
    ensure_git_repo(worktree)

    failures: list[str] = []

    def step(title: str, func) -> None:
        try:
            info(f"=== {title} ===")
            func()
        except Exception as error:
            failures.append(f"{title}: {error}")
            info(f"FAILED {title}: {error}")

    conf = data.get("configuration") or {}
    if conf.get("storage"):
        step(
            f"configuration: {conf.get('project') or 'configuration'}",
            lambda: pipeline.storage_sync(
                conf["storage"],
                worktree,
                project_name=conf.get("project") or "configuration",
                authors_file=Path(authors_file) if authors_file else None,
                domain=domain,
            ),
        )

    for ext in data.get("extension") or []:
        step(
            f"extension: {ext.get('project') or 'extension'}",
            lambda ext=ext: pipeline.storage_sync(
                ext["storage"],
                worktree,
                project_name=ext.get("project") or "extension",
                authors_file=Path(authors_file) if authors_file else None,
                domain=domain,
                extension=ext.get("name") or "",
                base_project=ext.get("base_project") or "",
            ),
        )

    external = data.get("external") or {}
    if not external.get("enabled"):
        if external:
            info("external: обработка отключена (enabled != true)")
    elif not external.get("xml_dir"):
        info("external: enabled=true, но xml_dir не задан — пропускаю")
    else:
        project = external.get("project") or "external"
        step(
            "external: EDT",
            lambda: pipeline.dp_xml_to_edt(
                Path(external["xml_dir"]),
                worktree / project,
                base_project=external.get("base_project") or "",
            ),
        )
        step(
            "external: commit EDT",
            lambda: commit_external(worktree, [project], "Внешние отчёты и обработки: обновление (EDT)"),
        )

    if failures:
        raise SyncConfigError("sync-all завершился с ошибками:\n  " + "\n  ".join(failures))
    info(f"sync-all done -> {worktree}")
