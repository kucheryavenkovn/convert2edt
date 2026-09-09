# Deprecated architecture

This is the previous generation of the 1C storage → EDT converter
(project `crs2edt`), kept for history and as a reserve reference only.

**Deprecated architecture. Replaced by `ibcmd` + `1cedtcli`.**

The active project (repository root) does NOT depend on anything in this
directory.

## Why it existed

The old pipeline needed `1cv8` DESIGNER (thick client) to read the 1C
configuration storage via gitsync, so it used:

- a Windows host with an installed licensed 1C:Enterprise;
- HTTP bridge (`host/bridge.py`) to launch DESIGNER on the Windows host
  from the Linux container;
- PowerShell host scripts and a Windows Service wrapper;
- VNC/GUI license activation inside a desktop base image.

## What replaced it

| Old component | Replacement |
|---|---|
| `1cv8 DESIGNER /DumpConfigToFiles` | `ibcmd infobase config export` |
| `1cv8 DESIGNER /LoadConfigFromFiles` | `ibcmd infobase config import` |
| `1cv8 DESIGNER /DumpCfg` | `ibcmd infobase config save` |
| `1cv8 DESIGNER /LoadCfg` | `ibcmd infobase config load` |
| Windows Host Bridge (`host/bridge.py`, `docker/wrapper/1cv8-host`) | not required |
| Windows 1C installation | Linux 1C server components (ibcmd) inside Docker |
| Local EDT / ring | `1cedtcli` inside Docker |
| gitsync + OneScript + plugins | out of scope for the converter (see old README below) |

## Contents (unchanged historical snapshot)

- `Dockerfile` / `Dockerfile.bridge` / `docker-compose.yml` — old builds;
- `host/` — Windows Host Bridge service (Python + PowerShell);
- `scripts/`, `docker/scripts/` — old entrypoint/doctor/migrate/sync and
  platform/EDT install scripts (the install scripts were reused in the new
  `docker/scripts/` with attribution);
- `docs/` — old SPEC and research notes, still useful as background.

Original README: [README.md](README.md)
