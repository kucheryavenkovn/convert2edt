#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1C Host Bridge (вариант B, docs/SPEC.md п.4).

Узкоспециализированный allowlisted HTTP-сервис: единственная функция — запуск
локального лицензированного 1cv8.exe в режиме DESIGNER/CREATEINFOBASE по запросу
из Docker-контейнера (wrapper /usr/local/bin/1cv8-host).

Только stdlib (без pip-зависимостей). Как Windows-сервис — см. bridge_service.py.

API:
  GET  /health        -> {"status","platform","licenseCheck","storageAccess"}
  GET  /platforms     -> {"platforms": [{"version","path"}]}
  POST /designer/run  -> {"args": ["DESIGNER", ...]} => {"exitCode","stdout","stderr","duration"}

Безопасность:
  - Bearer token (обязателен, если слушаем не-loopback);
  - запуск ТОЛЬКО 1cv8.exe, ТОЛЬКО DESIGNER|CREATEINFOBASE, allowlist ключей;
  - значения-пути обязаны маппиться из docker-путей (/bridge, /storage) и попадать
    под bridgeRoot или allowedStorages; '..' и абсолютные windows-пути из запроса запрещены;
  - никаких shell/cmd/powershell, запуск через CreateProcess (subprocess, список аргументов);
  - таймаут на job, MAX_CONCURRENT_JOBS=1, логи без паролей.
"""

import argparse
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------- константы

MODES = {"DESIGNER", "CREATEINFOBASE"}

# Ключ, значение — путь (docker-префикс), маппится и проверяется по корням
PATH_PAIR_KEYS = {
    "/Out",
    "/ConfigurationRepositoryF",
    "/ConfigurationRepositoryReport",
    "/ConfigurationRepositoryDumpCfg",
    "/DumpConfigToFiles",
    "/LoadCfg",
    "-listFile",
    "-configDumpInfoForChanges",
}
# Ключ, значение — не-путь
VALUE_PAIR_KEYS = {
    "/ConfigurationRepositoryN": None,
    "/ConfigurationRepositoryP": None,
    "-NBegin": re.compile(r"^\d+$"),
    "-NEnd": re.compile(r"^\d+$"),
    "-v": re.compile(r"^\d+$"),
    "-format": {"Hierarchical"},
    "-Extension": None,
    "-ReportFormat": {"mxl", "txt"},
}
# Слитные ключи: префикс -> значение является путём (маппится) или нет
ATTACHED_PATH_KEYS = ("/F", "/UseTemplate")
ATTACHED_PLAIN_KEYS = ("/N", "/P", "/UC", "/C", "/L", "/VL", "/AddInList", "/WA")
# Флаги и команды без значения
FLAG_KEYS = {
    "-force", "-update", "-NoTruncate", "-IncludeCommentLinesWithDoubleSlash",
    "-AllExtensions", "/DisableStartupMessages", "/DisableStartupDialogs",
    "/LRU", "/VLRU", "/WA+", "-configuredFromFiles",
}
COMMAND_KEYS = {
    "/ConfigurationRepositoryUpdateCfg", "/ConfigurationRepositoryReport",
    "/ConfigurationRepositoryDumpCfg", "/ConfigurationRepositoryBindCfg",
    "/ConfigurationRepositoryUnbindCfg", "/DumpConfigToFiles", "/LoadCfg",
}
SECRET_PAIR_KEYS = {"/ConfigurationRepositoryP", "/P"}
SECRET_PAIR_PREFIXES = ("/P", "/ConfigurationRepositoryP")

MAX_BODY = 512 * 1024

# ---------------------------------------------------------------- конфигурация

DEFAULT_CONFIG = {
    "listen": "127.0.0.1:17833",
    "token": "",
    "platformVersion": "auto",          # auto | 8.3.27 | 8.3.27.2342
    "platformRoots": [
        r"C:\Program Files\1cv8",
        r"C:\Program Files (x86)\1cv8",
    ],
    "allowedStorages": [r"E:\crs\gitsync"],
    "bridgeRoot": r"E:\1c-bridge",
    "pathMappings": [
        {"docker": "/bridge", "windows": r"E:\1c-bridge"},
        {"docker": "/storage", "windows": r"E:\crs\gitsync"},
    ],
    "timeoutSeconds": 1800,
    "maxConcurrentJobs": 1,
    "logFile": r"E:\1c-bridge\bridge.log",
    "licenseSmoke": {"enabled": True, "cacheSeconds": 300},
}


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
    return cfg


# ---------------------------------------------------------------- платформы

_VERSION_RE = re.compile(r"^8\.\d+\.\d+\.\d+$")


def discover_platforms(cfg):
    found = []
    for root in cfg["platformRoots"]:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            exe = os.path.join(root, name, "bin", "1cv8.exe")
            if _VERSION_RE.match(name) and os.path.isfile(exe):
                found.append({"version": name, "path": exe})
    found.sort(key=lambda p: [int(x) for x in p["version"].split(".")])
    return found


def select_platform(cfg, platforms):
    want = str(cfg.get("platformVersion") or "auto").strip()
    if want.lower() == "auto":
        return platforms[-1] if platforms else None
    exact = [p for p in platforms if p["version"] == want]
    if exact:
        return exact[-1]
    prefix = [p for p in platforms if p["version"].startswith(want + ".")]
    if prefix:
        return prefix[-1]
    return None


# ---------------------------------------------------------------- пути

def normalize_win(path):
    return os.path.normpath(path).lower().rstrip("\\")


def is_under(path, root):
    p = normalize_win(path)
    r = normalize_win(root)
    return p == r or p.startswith(r + "\\")


def map_docker_path(value, cfg):
    """docker-путь -> windows-путь; None, если не смаппился."""
    v = value.replace("\\", "/")
    mappings = sorted(cfg["pathMappings"], key=lambda m: -len(m["docker"]))
    for m in mappings:
        d = m["docker"].rstrip("/")
        if v == d or v.startswith(d + "/"):
            rest = v[len(d):].lstrip("/")
            if ".." in rest.split("/"):
                return None
            return os.path.normpath(os.path.join(m["windows"], rest))
    return None


class BridgeError(Exception):
    def __init__(self, http_code, message):
        super().__init__(message)
        self.http_code = http_code
        self.message = message


def classify(value):
    v = value.lstrip()
    if v.startswith("/"):
        return "abs"
    if re.match(r"^[A-Za-z]:[\\/]", v):
        return "winabs"
    if v.startswith("\\\\"):
        return "unc"
    return "other"


# ---------------------------------------------------------------- валидация argv

def validate_and_map_args(args, cfg):
    """Возвращает windows-argv (список строк) или кидает BridgeError."""
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise BridgeError(400, "args должен быть непустым массивом строк")
    if any("\x00" in a for a in args):
        raise BridgeError(400, "NUL в аргументах запрещён")

    mode = args[0].upper()
    if mode not in MODES:
        raise BridgeError(400, "Поддерживаются только режимы DESIGNER/CREATEINFOBASE, получено: %r" % args[0])

    win_args = [mode]
    i = 1
    n = len(args)
    seen_storage_f = None

    while i < n:
        a = args[i]

        # CREATEINFOBASE: File=<путь>
        if a.startswith("File="):
            if mode != "CREATEINFOBASE":
                raise BridgeError(400, "File= допустим только в режиме CREATEINFOBASE")
            win_path = map_docker_path(a[5:], cfg)
            if win_path is None:
                raise BridgeError(400, "Путь ИБ не маппится в bridgeRoot: %s" % a[5:])
            if not is_under(win_path, cfg["bridgeRoot"]):
                raise BridgeError(400, "Путь ИБ вне bridgeRoot: %s" % win_path)
            win_args.append("File=" + win_path)
            i += 1
            continue

        # раздельные пары
        if a in PATH_PAIR_KEYS:
            if i + 1 >= n:
                raise BridgeError(400, "Ключ %s без значения" % a)
            val = args[i + 1]
            kind = classify(val)
            if kind in ("winabs", "unc", "abs"):
                raise BridgeError(400, "Значение %s должно быть docker-путем через pathMappings, получено: %s" % (a, val))
            win_path = map_docker_path(val, cfg)
            if win_path is None:
                raise BridgeError(400, "Путь не маппится (pathMappings): %s %s" % (a, val))
            if a == "/ConfigurationRepositoryF":
                if not any(is_under(win_path, s) for s in cfg["allowedStorages"]):
                    raise BridgeError(400, "Хранилище не входит в allowedStorages: %s" % win_path)
                seen_storage_f = win_path
            elif a == "/Out" or a.startswith("-"):
                if not is_under(win_path, cfg["bridgeRoot"]) and not any(
                    is_under(win_path, s) for s in cfg["allowedStorages"]
                ):
                    raise BridgeError(400, "Путь вне bridgeRoot/allowedStorages: %s" % win_path)
            else:
                if not is_under(win_path, cfg["bridgeRoot"]):
                    raise BridgeError(400, "Путь вне bridgeRoot: %s" % win_path)
            win_args.append(a)
            win_args.append(win_path)
            i += 2
            continue

        if a in VALUE_PAIR_KEYS:
            if i + 1 >= n:
                raise BridgeError(400, "Ключ %s без значения" % a)
            val = args[i + 1]
            rule = VALUE_PAIR_KEYS[a]
            if rule is not None:
                if isinstance(rule, set) and val not in rule:
                    raise BridgeError(400, "Недопустимое значение %s для %s" % (val, a))
                if hasattr(rule, "match") and not rule.match(val):
                    raise BridgeError(400, "Недопустимое значение %s для %s" % (val, a))
            if classify(val) in ("winabs", "unc"):
                raise BridgeError(400, "Windows-путь в значении %s запрещён" % a)
            win_args.append(a)
            win_args.append(val)
            i += 2
            continue

        # слитные ключи
        if a.startswith(ATTACHED_PATH_KEYS):
            key = next(k for k in ATTACHED_PATH_KEYS if a.startswith(k))
            val = a[len(key):]
            if not val:
                raise BridgeError(400, "Пустое значение у %s" % key)
            win_path = map_docker_path(val, cfg)
            if win_path is None:
                raise BridgeError(400, "Путь %s... не маппится через pathMappings" % key)
            if not is_under(win_path, cfg["bridgeRoot"]) and not any(
                is_under(win_path, s) for s in cfg["allowedStorages"]
            ):
                raise BridgeError(400, "Путь вне bridgeRoot/allowedStorages: %s" % win_path)
            win_args.append(key + win_path)
            i += 1
            continue

        if a.startswith(ATTACHED_PLAIN_KEYS):
            val = a[max(a.startswith(p) and len(p) for p in ATTACHED_PLAIN_KEYS):]
            if "\x00" in val:
                raise BridgeError(400, "NUL запрещён")
            if classify(val) in ("winabs", "unc"):
                raise BridgeError(400, "Windows-путь в значении ключа %s запрещён" % a)
            win_args.append(a)
            i += 1
            continue

        if a in FLAG_KEYS or a in COMMAND_KEYS:
            win_args.append(a)
            i += 1
            continue

        raise BridgeError(400, "Неизвестный/запрещённый аргумент: %r" % a)

    if mode == "CREATEINFOBASE" and not any(x.startswith("File=") for x in win_args):
        raise BridgeError(400, "CREATEINFOBASE требует File=<docker-путь>")
    if mode == "DESIGNER" and not any(x.startswith("/F") for x in win_args):
        raise BridgeError(400, "DESIGNER требует /F<docker-путь ИБ>")

    return win_args


def mask_args(win_args):
    out = []
    i = 0
    while i < len(win_args):
        a = win_args[i]
        if a in SECRET_PAIR_KEYS and i + 1 < len(win_args):
            out.append(a)
            out.append("****")
            i += 2
            continue
        if a.startswith(SECRET_PAIR_PREFIXES) and a not in FLAG_KEYS:
            out.append(a.split("=")[0] if "=" in a else a[:2] + "****")
            i += 1
            continue
        out.append(a)
        i += 1
    return out


# ---------------------------------------------------------------- выполнение

class Runner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.job_lock = threading.Lock()
        self.smoke_lock = threading.Lock()
        self.smoke_cache = (0, None)  # (ts, ok)

    def platforms(self):
        return discover_platforms(self.cfg)

    def selected(self):
        return select_platform(self.cfg, self.platforms())

    def run_designer(self, args):
        platforms = self.platforms()
        plat = select_platform(self.cfg, platforms)
        if not plat:
            raise BridgeError(500, "1C platform not found in %s" % self.cfg["platformRoots"])

        win_args = validate_and_map_args(args, self.cfg)
        job_id = uuid.uuid4().hex[:8]
        log = logging.getLogger("bridge")
        log.info("job=%s mode=%s platform=%s args=%s",
                 job_id, win_args[0], plat["version"], " ".join(mask_args(win_args)))

        if not self.job_lock.acquire(blocking=False):
            raise BridgeError(429, "Занято: уже выполняется другой job (maxConcurrentJobs=%s)"
                              % self.cfg["maxConcurrentJobs"])
        try:
            os.makedirs(self.cfg["bridgeRoot"], exist_ok=True)
            t0 = time.monotonic()
            proc = subprocess.Popen(
                [plat["path"]] + win_args,
                cwd=self.cfg["bridgeRoot"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            timeout = int(self.cfg["timeoutSeconds"])
            try:
                out, err = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    out, err = proc.communicate(timeout=30)
                except Exception:
                    out, err = b"", b""
                log.error("job=%s TIMEOUT after %ss", job_id, timeout)
                return {
                    "exitCode": 124,
                    "stdout": "Host Bridge: job timeout after %ss (1cv8 terminated)" % timeout,
                    "stderr": "",
                    "duration": round(time.monotonic() - t0, 1),
                    "jobId": job_id,
                    "timeout": True,
                }
            duration = round(time.monotonic() - t0, 1)
            log.info("job=%s exitCode=%s duration=%ss", job_id, exit_code, duration)
            return {
                "exitCode": exit_code,
                "stdout": (out or b"").decode("utf-8", errors="replace"),
                "stderr": (err or b"").decode("utf-8", errors="replace"),
                "duration": duration,
                "jobId": job_id,
            }
        finally:
            self.job_lock.release()

    def license_smoke(self):
        """Реальный smoke: CREATEINFOBASE во временном каталоге bridgeRoot."""
        enabled = self.cfg.get("licenseSmoke", {}).get("enabled", True)
        if not enabled:
            return "disabled"
        cache_s = int(self.cfg.get("licenseSmoke", {}).get("cacheSeconds", 300))
        with self.smoke_lock:
            ts, cached = self.smoke_cache
            if cached is not None and time.time() - ts < cache_s:
                return "ok" if cached else "fail"
            plat = self.selected()
            if not plat:
                self.smoke_cache = (time.time(), False)
                return "fail"
            smoke_dir = os.path.join(self.cfg["bridgeRoot"], ".health-smoke")
            ib = os.path.join(smoke_dir, "ib")
            out = os.path.join(smoke_dir, "out.txt")
            try:
                os.makedirs(ib, exist_ok=True)
                if os.path.isfile(out):
                    os.remove(out)
                proc = subprocess.run(
                    [plat["path"], "CREATEINFOBASE", "File=" + ib, "/Out", out,
                     "/DisableStartupMessages", "/DisableStartupDialogs"],
                    cwd=self.cfg["bridgeRoot"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=300,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                text = ""
                if os.path.isfile(out):
                    with open(out, "r", encoding="utf-8-sig", errors="replace") as f:
                        text = f.read()
                ok = proc.returncode == 0 and not re.search(r"лиценз|license", text, re.I)
            except Exception:
                ok = False
            self.smoke_cache = (time.time(), ok)
            return "ok" if ok else "fail"

    def health(self):
        plat = self.selected()
        storage_ok = all(os.path.isdir(s) for s in self.cfg["allowedStorages"])
        return {
            "status": "ok" if plat and storage_ok else "degraded",
            "platform": plat["version"] if plat else None,
            "licenseCheck": self.license_smoke(),
            "storageAccess": "ok" if storage_ok else "fail",
        }


# ---------------------------------------------------------------- HTTP

def make_handler(cfg, runner):
    class Handler(BaseHTTPRequestHandler):
        server_version = "1C-Bridge/1.0"
        protocol_version = "HTTP/1.1"

        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self):
            token = str(cfg.get("token") or "")
            loopback = self.client_address[0] in ("127.0.0.1", "::1")
            if not token:
                if not loopback:
                    self._send(403, {"error": "token не настроен; listen не на loopback"})
                    return False
                return True
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                self._send(401, {"error": "Authorization: Bearer required"})
                return False
            if not hmac.compare_digest(auth[7:].strip(), token):
                self._send(403, {"error": "invalid token"})
                return False
            return True

        def log_message(self, fmt, *args):
            logging.getLogger("bridge.http").info("%s %s", self.client_address[0], fmt % args)

        def do_GET(self):
            if not self._check_auth():
                return
            if self.path == "/health":
                self._send(200, runner.health())
            elif self.path == "/platforms":
                self._send(200, {"platforms": runner.platforms()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._check_auth():
                return
            if self.path != "/designer/run":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"error": "bad content-length"})
                return
            raw = self.rfile.read(length)
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, {"error": "invalid json"})
                return
            try:
                result = runner.run_designer(req.get("args"))
                self._send(200, result)
            except BridgeError as e:
                logging.getLogger("bridge").warning("rejected: %s", e.message)
                self._send(e.http_code, {"error": e.message})

        def do_PUT(self):
            self._send(405, {"error": "method not allowed"})

        do_DELETE = do_PUT
        do_PATCH = do_PUT

    return Handler


def setup_logging(cfg):
    log = logging.getLogger("bridge")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        os.makedirs(os.path.dirname(cfg["logFile"]), exist_ok=True)
        fh = RotatingFileHandler(cfg["logFile"], maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    http_log = logging.getLogger("bridge.http")
    http_log.setLevel(logging.INFO)
    http_log.addHandler(sh)


def main():
    ap = argparse.ArgumentParser(description="1C Host Bridge")
    ap.add_argument("--config", default=None, help="путь к bridge_config.json")
    ap.add_argument("--check", action="store_true", help="проверить конфиг и окружение, не поднимая сервер")
    args = ap.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg)
    runner = Runner(cfg)

    if args.check:
        plats = runner.platforms()
        sel = runner.selected()
        print("platforms:", json.dumps(plats, ensure_ascii=False, indent=2))
        print("selected:", sel)
        print("bridgeRoot:", cfg["bridgeRoot"], "writable:", os.access(cfg["bridgeRoot"], os.W_OK)
              if os.path.isdir(cfg["bridgeRoot"]) else "(нет, будет создан)")
        print("storages:", [(s, os.path.isdir(s)) for s in cfg["allowedStorages"]])
        print("licenseSmoke:", runner.license_smoke())
        return 0

    host, port = cfg["listen"].rsplit(":", 1)
    os.makedirs(cfg["bridgeRoot"], exist_ok=True)
    httpd = ThreadingHTTPServer((host, int(port)), make_handler(cfg, runner))
    logging.getLogger("bridge").info("1C Host Bridge listening on %s (platform=%s)",
                                     cfg["listen"], (runner.selected() or {}).get("version"))
    httpd.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
