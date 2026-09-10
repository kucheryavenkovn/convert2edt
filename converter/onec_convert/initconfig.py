import html
import json
import subprocess
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .proc import info

CONFIG_TEMPLATE = """# sync.toml — сгенерировано 1c-convert init-config / config-server
# Пути указываются ВНУТРИ контейнера (см. монтирования в compose.yaml).

[worktree]
path = "{worktree}"
{authors_line}

[configuration]
storage = "{config_storage}"
project = "{config_project}"
{extension_sections}
[external]
{external_lines}"""

EXTENSION_TEMPLATE = """[[extension]]
name = "{name}"
storage = "{storage}"
project = "{project}"
base_project = "{base_project}"

"""

DEFAULTS = {
    "worktree": "/work/output/storage-git",
    "authors_file": "",
    "domain": "storage.local",
    "config_storage": "/work/fixtures/crs/cf",
    "config_project": "configuration",
    "extensions": [],
    "external_enabled": True,
    "external_xml_dir": "/work/fixtures/dp-xml",
    "external_project": "external",
}


def render_toml(data: dict) -> str:
    worktree = data.get("worktree") or DEFAULTS["worktree"]
    authors_file = data.get("authors_file") or ""
    domain = data.get("domain") or "storage.local"
    config_storage = data.get("config_storage") or DEFAULTS["config_storage"]
    config_project = data.get("config_project") or "configuration"

    authors_line = ""
    if authors_file:
        authors_line = f'authors_file = "{authors_file}"\ndomain = "{domain}"'
    else:
        authors_line = f'# authors_file = "/work/authors.txt"\ndomain = "{domain}"'

    extension_sections = ""
    for ext in data.get("extensions") or []:
        base = ext.get("base_project") or config_project
        extension_sections += EXTENSION_TEMPLATE.format(
            name=ext.get("name") or "Расширение1",
            storage=ext.get("storage") or "/work/fixtures/crs/ext/Расширение1",
            project=ext.get("project") or "extension",
            base_project=base,
        )

    enabled = "true" if data.get("external_enabled") else "false"
    xml_dir = data.get("external_xml_dir") or ""
    project = data.get("external_project") or "external"
    base = data.get("external_base_project") or config_project
    external_lines = (
        f'enabled = {enabled}\n'
        f'xml_dir = "{xml_dir}"\n'
        f'project = "{project}"\n'
        f'base_project = "{base}"'
    )

    return CONFIG_TEMPLATE.format(
        worktree=worktree,
        authors_line=authors_line,
        config_storage=config_storage,
        config_project=config_project,
        extension_sections=extension_sections,
        external_lines=external_lines,
    )


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        value = ""
    return value or default


def wizard() -> dict:
    print("=== 1c-convert: мастер создания sync.toml ===")
    print("Enter = принять значение по умолчанию. Пути — внутри контейнера.\n")

    data = {
        "worktree": _ask("git-worktree (монорепо)", DEFAULTS["worktree"]),
        "authors_file": _ask("файл мапинга авторов (пусто = нет)", ""),
        "domain": _ask("домен email для неизвестных авторов", DEFAULTS["domain"]),
        "config_storage": _ask(
            "хранилище конфигурации", DEFAULTS["config_storage"]
        ),
        "config_project": _ask(
            "имя проекта конфигурации (= имя каталога в worktree)",
            DEFAULTS["config_project"],
        ),
        "extensions": [],
    }

    index = 1
    while True:
        print(f"\n--- расширение #{index} (Enter в имени = закончить) ---")
        name = _ask("имя расширения", "")
        if not name:
            break
        default_storage = f"/work/fixtures/crs/ext/{name}"
        data["extensions"].append(
            {
                "name": name,
                "storage": _ask("хранилище расширения", default_storage),
                "project": _ask("имя проекта расширения", f"extension-{name}"),
                "base_project": _ask(
                    "базовый проект (EDT)", data["config_project"]
                ),
            }
        )
        index += 1

    print("\n--- внешние отчёты и обработки ---")
    enabled = _ask("выгружать обработки в EDT-проект? (1=да, 0=нет)", "1")
    data["external_enabled"] = enabled.strip() == "1"
    if data["external_enabled"]:
        data["external_xml_dir"] = _ask(
            "каталог XML внешних обработок", DEFAULTS["external_xml_dir"]
        )
        data["external_project"] = _ask(
            "имя EDT-проекта внешних обработок", DEFAULTS["external_project"]
        )
        data["external_base_project"] = _ask(
            "базовый проект (EDT)", data["config_project"]
        )
    return data


class SyncRunner:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.lines: deque[str] = deque(maxlen=5000)
        self.status = "idle"

    def start(self, config_path: Path) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                raise RuntimeError("синхронизация уже выполняется")
            self.lines.clear()
            self.status = "running"
            self.proc = subprocess.Popen(
                ["1c-convert", "sync-all", "--config", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))
        code = self.proc.wait()
        self.status = "done" if code == 0 else f"failed (код {code})"
        info(f"config-server: sync finished: {self.status}")

    def snapshot(self, after: int = 0) -> dict:
        with self.lock:
            items = list(self.lines)
            running = self.proc is not None and self.proc.poll() is None
        return {
            "status": self.status if not running else "running",
            "total": len(items),
            "lines": items[after:],
        }


RUNNER = SyncRunner()


def read_state(data: dict) -> dict:
    from .pipeline import run_git

    worktree = Path(data.get("worktree") or "/work/output/storage-git")
    result: dict = {"worktree": str(worktree), "exists": worktree.is_dir()}
    if not result["exists"]:
        return result
    state_file = worktree / ".storage-sync.json"
    projects: dict = {}
    if state_file.is_file():
        try:
            projects = json.loads(state_file.read_text(encoding="utf-8")).get("projects", {})
        except (OSError, ValueError):
            projects = {}
    result["projects"] = projects
    result["dirs"] = sorted(
        item.name for item in worktree.iterdir() if item.is_dir() and item.name != ".git"
    )
    commits = []
    if (worktree / ".git").exists():
        try:
            out = run_git(
                worktree,
                "log",
                "-15",
                "--format=%h%x09%ad%x09%an%x09%s",
                "--date=short",
            )
            for line in out.splitlines():
                parts = line.split("\t", 3)
                if len(parts) == 4:
                    commits.append(
                        {
                            "hash": parts[0],
                            "date": parts[1],
                            "author": parts[2],
                            "message": parts[3],
                        }
                    )
        except RuntimeError:
            commits = []
    result["commits"] = commits
    return result


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>1c-convert — sync.toml</title>
<style>
 body{font-family:sans-serif;max-width:860px;margin:24px auto;padding:0 12px;background:#f6f7f9}
 h1{font-size:1.3rem} h2{font-size:1.05rem;margin-top:24px}
 fieldset{margin:12px 0;border:1px solid #ccd;border-radius:8px;background:#fff}
 legend{font-weight:600;padding:0 6px}
 label{display:block;margin:6px 0 2px;font-size:.9rem;color:#333}
 input{width:100%;box-sizing:border-box;padding:6px;border:1px solid #bbc;border-radius:4px}
 .ext{border-left:4px solid #7aa;padding:6px 10px;margin:8px 0;background:#eef}
 button{margin-top:10px;padding:8px 16px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer}
 button.mini{background:#9333ea;padding:4px 10px}
 button.green{background:#16a34a}
 pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;overflow:auto;max-height:340px}
 .hint{color:#777;font-size:.85rem}
 .state{background:#fff;border:1px solid #ccd;border-radius:8px;padding:10px;margin:8px 0}
 .pill{display:inline-block;background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:2px 10px;margin:2px;font-size:.85rem}
 .cur{font-weight:600;color:#2563eb;white-space:pre-wrap}
 table{border-collapse:collapse;width:100%;font-size:.85rem;background:#fff}
 td,th{border-bottom:1px solid #e2e8f0;padding:4px 6px;text-align:left}
</style></head><body>
<h1>1c-convert — конфигурация и запуск синхронизации</h1>
<p class="hint">Пути — внутри контейнера. Базовый проект расширений/обработок подставляется из имени проекта конфигурации.</p>
<form id="f">
<fieldset><legend>Монорепозиторий</legend>
 <label>git-worktree <input name="worktree" value="/work/output/storage-git"></label>
 <label>Файл авторов <input name="authors_file" placeholder="/work/authors.txt"></label>
 <label>Домен email <input name="domain" value="storage.local"></label>
</fieldset>
<fieldset><legend>Хранилище конфигурации</legend>
 <label>Путь к хранилищу <input name="config_storage" value="/work/fixtures/crs/cf"></label>
 <label>Имя проекта <input name="config_project" value="configuration" id="cp"></label>
</fieldset>
<fieldset><legend>Расширения</legend><div id="exts"></div>
 <button type="button" class="mini" onclick="addExt()">+ расширение</button>
</fieldset>
<fieldset><legend>Внешние отчёты и обработки</legend>
 <label><input type="checkbox" name="external_enabled" id="exen" style="width:auto" checked> выгружать обработки в EDT-проект</label>
 <label>Каталог XML (выгрузка Конфигуратора) <input name="external_xml_dir" value="/work/fixtures/dp-xml"></label>
 <label>Имя EDT-проекта <input name="external_project" value="external"></label>
 <label>Базовый проект (EDT) <input name="external_base_project" id="ebp"></label>
</fieldset>
<button type="button" onclick="send(false)">Предпросмотр TOML</button>
<button type="button" onclick="send(true)">Сохранить в файл</button>
<button type="button" onclick="state()">Показать состояние</button>
<button type="button" class="green" onclick="runSync()">▶ Запустить синхронизацию</button>
</form>
<h2>Состояние (что уже выгружено из хранилищ)</h2><div id="state" class="state">— нажмите «Показать состояние» —</div>
<h2>Ход синхронизации</h2><div id="cur" class="cur">—</div>
<pre id="out">— заполните форму и нажмите «Предпросмотр» —</pre>
<pre id="log" style="display:none"></pre>
<script>
const $=n=>document.querySelector(n);
function formData(){
 const f=document.getElementById('f'), data=Object.fromEntries(new FormData(f));
 data.extensions=[...document.querySelectorAll('.ext')].map(e=>({
  name:e.querySelector('[name=ext_name]').value,
  storage:e.querySelector('[name=ext_storage]').value,
  project:e.querySelector('[name=ext_project]').value,
  base_project:e.querySelector('[name=ext_base]').value||$('#cp').value
 }));
 return data;
}
function syncBases(){ $('#ebp').value=$('#cp').value;
 document.querySelectorAll('.ext [name=ext_base]').forEach(i=>{ if(!i.dataset.touched) i.value=$('#cp').value; }); }
$('#cp').addEventListener('input',syncBases);
$('#ebp').addEventListener('input',()=>{});
function addExt(){
 const d=document.createElement('div');d.className='ext';
 d.innerHTML='<label>Имя <input name="ext_name"></label>'
  +'<label>Хранилище <input name="ext_storage"></label>'
  +'<label>Проект <input name="ext_project"></label>'
  +'<label>Базовый проект (EDT) <input name="ext_base"></label>';
 document.getElementById('exts').appendChild(d);
 d.querySelector('[name=ext_base]').value=$('#cp').value;
 d.querySelector('[name=ext_base]').addEventListener('input',e=>e.target.dataset.touched=1);
}
async function send(save){
 const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({save:!!save,data:formData()})});
 const j=await r.json();
 document.getElementById('out').textContent=j.toml||j.error;
}
async function state(){
 const r=await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({data:formData()})});
 renderState(await r.json());
}
function renderState(s){
 if(!s.exists){ $('#state').textContent='worktree не существует: '+s.worktree+' (будет создан при синхронизации)'; return; }
 let h='<div>Проекты (последняя синхронизированная версия хранилища):</div>';
 if(s.projects&&Object.keys(s.projects).length){
  for(const [p,v] of Object.entries(s.projects)) h+='<span class="pill">'+p+': версия '+v+'</span>';
 } else h+='<span class="pill">пока ничего не синхронизировано</span>';
 if(s.dirs) h+='<div class="hint">каталоги: '+s.dirs.join(', ')+'</div>';
 if(s.commits&&s.commits.length){
  h+='<table><tr><th>hash</th><th>дата</th><th>автор</th><th>комментарий</th></tr>';
  for(const c of s.commits) h+='<tr><td>'+c.hash+'</td><td>'+c.date+'</td><td>'+c.author+'</td><td>'+c.message+'</td></tr>';
  h+='</table>';
 }
 $('#state').innerHTML=h;
}
let logPos=0, timer=null;
async function runSync(){
 const r=await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({data:formData()})});
 const j=await r.json();
 if(j.error){ $('#cur').textContent='ОШИБКА: '+j.error; return; }
 logPos=0; $('#log').style.display='block'; $('#log').textContent='';
 $('#cur').textContent='запущено...';
 if(timer) clearInterval(timer);
 timer=setInterval(poll,1200);
}
async function poll(){
 const r=await fetch('/api/sync/log?after='+logPos);
 const j=await r.json();
 logPos=j.total;
 if(j.lines&&j.lines.length) $('#log').textContent+=j.lines.join('\\n')+'\\n';
 $('#log').scrollTop=$('#log').scrollHeight;
 const cur=j.lines?j.lines.filter(l=>l.includes('--- version')||l.includes('syncing')||l.includes('sync done')||l.includes('committed')):[];
 if(cur.length) $('#cur').textContent=cur[cur.length-1];
 if(j.status!=='running'){ clearInterval(timer); timer=null; $('#cur').textContent='ГОТОВО: '+j.status; state(); }
}
syncBases(); state();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    out_path = Path("/work/sync.toml")

    def log_message(self, fmt, *args):
        info(f"config-server: {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path.startswith("/api/sync/log"):
            after = 0
            if "after=" in self.path:
                try:
                    after = int(self.path.split("after=")[1].split("&")[0])
                except ValueError:
                    after = 0
            self._json(200, RUNNER.snapshot(after))
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path == "/api/generate":
            payload = self._body()
            try:
                toml = render_toml(payload.get("data") or {})
            except Exception as error:
                self._json(400, {"error": str(error)})
                return
            saved = ""
            if payload.get("save"):
                try:
                    self.out_path.write_text(toml, encoding="utf-8")
                    saved = f"\n# сохранено: {self.out_path}"
                    info(f"config-server: saved {self.out_path}")
                except OSError as error:
                    saved = f"\n# ошибка сохранения: {html.escape(str(error))}"
            self._json(200, {"toml": toml + saved})
            return
        if self.path == "/api/state":
            self._json(200, read_state(self._body().get("data") or {}))
            return
        if self.path == "/api/sync":
            payload = self._body()
            data = payload.get("data") or {}
            try:
                toml = render_toml(data)
                self.out_path.write_text(toml, encoding="utf-8")
                RUNNER.start(self.out_path)
            except (RuntimeError, OSError, ValueError) as error:
                self._json(409, {"error": str(error)})
                return
            self._json(200, {"started": True, "config": str(self.out_path)})
            return
        self._send(404, b"not found", "text/plain")


def serve(host: str, port: int, out_path: Path | None = None) -> None:
    if out_path is not None:
        Handler.out_path = out_path
    server = ThreadingHTTPServer((host, port), Handler)
    info(f"config-server: http://{host}:{port}/ -> пишет {Handler.out_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        info("config-server: stopped")
