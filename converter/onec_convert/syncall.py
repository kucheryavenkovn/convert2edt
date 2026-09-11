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


ENGINES = ("tool1cd", "gitsync")


def _gitsync():
    from .gitsync import GitSync

    return GitSync()


def sync_all(cfg: Config, config_path: Path) -> None:
    data = _load(config_path)
    worktree_conf = data.get("worktree") or {}
    worktree = Path(worktree_conf.get("path") or "")
    if not str(worktree):
        raise SyncConfigError("[worktree] path is required in sync config")

    # engine = tool1cd (по умолчанию): нативный конвейер ctool1cd+ibcmd+1cedtcli;
    # engine = gitsync: хранилище -> git через oscript-library/gitsync (+edtExport),
    # каждый проект — отдельный git-репозиторий <worktree>/<project> (src-layout)
    engine = (worktree_conf.get("engine") or "tool1cd").strip().lower()
    if engine not in ENGINES:
        raise SyncConfigError(
            f"[worktree] engine must be one of {ENGINES}, got: {engine!r}"
        )
    info(f"engine: {engine}")

    # [gitsync] — селективные бэкенды gitsync-движка:
    #   storage_backend = configurator | ctool1cd (плагин tool1CD; Windows-only)
    #   xml_backend     = configurator | ibcmd     (плагин use-ibcmd)
    gitsync_conf = data.get("gitsync") or {}
    storage_backend = (gitsync_conf.get("storage_backend") or "configurator").strip().lower()
    xml_backend = (gitsync_conf.get("xml_backend") or "configurator").strip().lower()
    ib_connection = gitsync_conf.get("ib_connection") or ""
    ib_user = gitsync_conf.get("ib_user") or ""
    ib_pwd = gitsync_conf.get("ib_pwd") or ""
    ibcmd_db = {k: gitsync_conf.get(f"ibcmd_{k}") or "" for k in
                ("dbms", "db_server", "db_name", "db_user", "db_pwd")}
    if engine == "gitsync":
        from .gitsync import STORAGE_BACKENDS, XML_BACKENDS

        if storage_backend not in STORAGE_BACKENDS:
            raise SyncConfigError(
                f"[gitsync] storage_backend must be one of {STORAGE_BACKENDS}, "
                f"got: {storage_backend!r}"
            )
        if xml_backend not in XML_BACKENDS:
            raise SyncConfigError(
                f"[gitsync] xml_backend must be one of {XML_BACKENDS}, "
                f"got: {xml_backend!r}"
            )
        info(f"gitsync backends: storage={storage_backend}, xml={xml_backend}")

    authors_file = worktree_conf.get("authors_file") or None
    domain = worktree_conf.get("domain") or "storage.local"

    pipeline = Pipeline(cfg)
    external = data.get("external") or {}
    if engine == "tool1cd" or external.get("enabled"):
        ensure_git_repo(worktree)

    failures: list[str] = []

    def step(title: str, func) -> None:
        try:
            info(f"=== {title} ===")
            func()
        except Exception as error:
            failures.append(f"{title}: {error}")
            info(f"FAILED {title}: {error}")

    def sync_section(section: dict, default_project: str, extension: str = "") -> None:
        project = section.get("project") or default_project
        if engine == "gitsync":
            _gitsync().sync_project(
                section["storage"],
                worktree / project,
                project,
                storage_user=section.get("storage_user") or "Администратор",
                storage_pwd=section.get("storage_pwd") or "",
                extension=extension,
                domain=domain,
                storage_backend=storage_backend,
                xml_backend=xml_backend,
                ib_connection=ib_connection,
                ib_user=ib_user,
                ib_pwd=ib_pwd,
                **ibcmd_db,
            )
        else:
            pipeline.storage_sync(
                section["storage"],
                worktree,
                project_name=project,
                authors_file=Path(authors_file) if authors_file else None,
                domain=domain,
                extension=extension,
                base_project=section.get("base_project") or "",
            )

    conf = data.get("configuration") or {}
    if not conf.get("enabled", True):
        info("configuration: шаг отключён (enabled = false)")
    elif conf.get("storage"):
        step(
            f"configuration: {conf.get('project') or 'configuration'}",
            lambda: sync_section(conf, "configuration"),
        )

    for ext in data.get("extension") or []:
        if not ext.get("enabled", True):
            info(f"extension {ext.get('name') or ext.get('project') or '?'}: шаг отключён (enabled = false)")
            continue
        if not ext.get("storage"):
            continue
        step(
            f"extension: {ext.get('project') or 'extension'}",
            lambda ext=ext: sync_section(ext, "extension", extension=ext.get("name") or ""),
        )

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
