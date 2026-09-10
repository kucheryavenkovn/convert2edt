import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .detect import detect_source
from .env import Config
from .pipeline import Pipeline, edt_version, platform_version
from .proc import fail, info

SYNC_MODES = ("auto", "force", "off")


def path_arg(value: str) -> Path:
    return Path(value)


def sync_arg(value: str) -> str:
    if value not in SYNC_MODES:
        raise argparse.ArgumentTypeError(
            f"invalid sync mode: {value} (expected {'/'.join(SYNC_MODES)})"
        )
    return value


def cmd_info(args: argparse.Namespace) -> int:
    cfg = Config()
    print(f"1c-convert v{__version__} (ibcmd + 1cedtcli thin orchestrator)")
    print(f"  platform dir : /opt/1cv8/current -> {platform_version()}")
    ibcmd_bin = shutil.which("ibcmd")
    print(f"  ibcmd        : {ibcmd_bin or 'NOT FOUND'}")
    if ibcmd_bin:
        result = subprocess.run(
            [ibcmd_bin, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        first = (result.stdout or "").strip().splitlines()
        if first:
            print(f"  ibcmd version: {first[0].strip()}")
    edtcli_bin = shutil.which("1cedtcli")
    print(f"  1cedtcli     : {edtcli_bin or 'NOT FOUND'}")
    if edtcli_bin:
        print(f"  EDT version  : {edt_version()}")
    print(f"  V8 version   : {cfg.effective_v8_version() or 'auto'}")
    print(f"  temp root    : {cfg.temp_root}")
    print(f"  EDT ws root  : {cfg.edt_ws_root}")
    print(f"  locale       : {os.environ.get('LANG', 'default')}")
    return 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    from . import cli, detect, edtcli, env, ibcmd, pipeline, proc

    missing = [
        name
        for name in ("ibcmd", "1cedtcli", "java", "python3")
        if shutil.which(name) is None
    ]
    if missing:
        fail(f"selfcheck: binaries not found: {', '.join(missing)}")
    Config()
    print(f"selfcheck OK (1c-convert v{__version__})")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    try:
        source = detect_source(args.path)
    except ValueError as error:
        fail(str(error))
    print(source.describe())
    return 0


def cmd_storage_info(args: argparse.Namespace) -> int:
    from .pipeline import Pipeline
    from .tool1cd import Tool1CD, locate_storage_db, prepare_local_copy

    cfg = Config()
    pipeline = Pipeline(cfg)
    try:
        db = locate_storage_db(args.storage)
        temp = pipeline.temp("storage-info")
        local_db = prepare_local_copy(db, temp.root)
        tool = Tool1CD(cfg)
        versions = tool.versions(local_db, temp.root / "tables")
        users = tool.users(local_db, temp.root / "tables")
    except (ValueError, RuntimeError) as error:
        fail(str(error))
    print(f"storage : {db}")
    print(f"versions: {len(versions)} (#{versions[0].number}..#{versions[-1].number})")
    print("users   :")
    for userid, name in sorted(users.items(), key=lambda kv: kv[1]):
        print(f"  {name}  ({userid})")
    shown = versions[-args.limit :] if args.limit > 0 else versions
    print(f"last versions (up to {args.limit}):")
    for v in reversed(shown):
        author = users.get(v.userid, v.userid)
        comment = (v.comment or "").replace("\n", " ")
        print(f"  #{v.number}  {v.date}  {author}  {comment}")
    pipeline.finish_temp()
    return 0


def make_handler(build):
    def handler(args: argparse.Namespace) -> int:
        cfg = Config()
        pipeline = Pipeline(cfg)
        try:
            build(pipeline, args)
        except (ValueError, RuntimeError) as error:
            fail(str(error))
        return 0

    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="1c-convert",
        description=(
            "Thin orchestrator around official ibcmd and 1cedtcli. "
            "Conversion logic follows arkuznetsov/1CFilesConverter."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="show installed tool versions and paths")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("selfcheck", help="verify binaries and configuration")
    p.set_defaults(func=cmd_selfcheck)

    p = sub.add_parser("detect", help="detect 1C source type of a path")
    p.add_argument("path")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser(
        "cf-to-edt", help="1C configuration file (*.cf) -> 1C:EDT project"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.cf_to_edt(a.src, a.dst))
    )

    p = sub.add_parser(
        "edt-to-cf", help="1C:EDT project -> 1C configuration file (*.cf)"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.edt_to_cf(a.src, a.dst))
    )

    p = sub.add_parser(
        "cf-to-xml", help="1C configuration file (*.cf) -> 1C:Designer XML files"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.add_argument("--sync", type=sync_arg, default="auto")
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.cf_to_xml(a.src, a.dst, sync=a.sync))
    )

    p = sub.add_parser(
        "xml-to-cf", help="1C:Designer XML files -> 1C configuration file (*.cf)"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.xml_to_cf(a.src, a.dst))
    )

    p = sub.add_parser(
        "xml-to-edt", help="1C:Designer XML files -> 1C:EDT project (no infobase)"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.xml_to_edt(a.src, a.dst))
    )

    p = sub.add_parser(
        "edt-to-xml", help="1C:EDT project -> 1C:Designer XML files (no infobase)"
    )
    p.add_argument("src", type=path_arg)
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.edt_to_xml(a.src, a.dst))
    )

    p = sub.add_parser(
        "ib-to-xml",
        help="infobase (/F<path>, /S<server>\\<ref> or dir with 1cv8.1cd) -> 1C:Designer XML files",
    )
    p.add_argument("src")
    p.add_argument("dst", type=path_arg)
    p.add_argument("--sync", type=sync_arg, default="auto")
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.ib_to_xml(a.src, a.dst, sync=a.sync))
    )

    p = sub.add_parser(
        "ib-to-edt", help="infobase -> 1C:EDT project"
    )
    p.add_argument("src")
    p.add_argument("dst", type=path_arg)
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.ib_to_edt(a.src, a.dst))
    )

    p = sub.add_parser(
        "storage-info",
        help="1C configuration storage: versions, users, dates, comments",
    )
    p.add_argument("storage")
    p.add_argument("--limit", type=int, default=10, help="last N versions to show")
    p.set_defaults(func=cmd_storage_info)

    p = sub.add_parser(
        "storage-to-cf",
        help="configuration storage -> 1C configuration file (*.cf) of a given version",
    )
    p.add_argument("storage")
    p.add_argument("dst", type=path_arg)
    p.add_argument("--version", type=int, default=0, help="0 = latest")
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.storage_to_cf(a.storage, a.dst, a.version))
    )

    p = sub.add_parser(
        "storage-to-xml",
        help="configuration storage -> 1C:Designer XML files of a given version",
    )
    p.add_argument("storage")
    p.add_argument("dst", type=path_arg)
    p.add_argument("--version", type=int, default=0, help="0 = latest")
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.storage_to_xml(a.storage, a.dst, a.version))
    )

    p = sub.add_parser(
        "storage-to-edt",
        help="configuration storage -> 1C:EDT project of a given version",
    )
    p.add_argument("storage")
    p.add_argument("dst", type=path_arg)
    p.add_argument("--version", type=int, default=0, help="0 = latest")
    p.set_defaults(
        func=make_handler(lambda pl, a: pl.storage_to_edt(a.storage, a.dst, a.version))
    )

    p = sub.add_parser(
        "storage-sync",
        help="configuration storage -> git history (1C:EDT project, 1 version = 1 commit)",
    )
    p.add_argument("storage")
    p.add_argument("worktree", type=path_arg, help="git worktree directory")
    p.add_argument("--project-name", default="configuration")
    p.add_argument("--from-version", type=int, default=0, help="0 = resume after synced")
    p.add_argument("--to-version", type=int, default=0, help="0 = latest")
    p.add_argument("--authors", type=path_arg, default=None, help="file: StorageName=Git Name <email>")
    p.add_argument("--domain", default="storage.local", help="email domain for unmapped authors")
    p.add_argument(
        "--extension",
        default="",
        help="sync a configuration extension storage (extension name)",
    )
    p.set_defaults(
        func=make_handler(
            lambda pl, a: pl.storage_sync(
                a.storage,
                a.worktree,
                project_name=a.project_name,
                version_from=a.from_version,
                version_to=a.to_version,
                authors_file=a.authors,
                domain=a.domain,
                extension=a.extension,
            )
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        fail("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
