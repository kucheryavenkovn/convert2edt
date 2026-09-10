import html
import json
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
    "external_dir": "/work/fixtures/erf",
    "external_sources": "external-src",
    "external_xml_dir": "",
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

    external_lines = []
    if data.get("external_dir"):
        external_lines.append(
            f'dir = "{data["external_dir"]}"\nsources = "{data.get("external_sources") or "external-src"}"'
        )
    if data.get("external_xml_dir"):
        external_lines.append(
            f'xml_dir = "{data["external_xml_dir"]}"\n'
            f'project = "{data.get("external_project") or "external"}"\n'
            f'base_project = "{data.get("external_base_project") or config_project}"'
        )
    if not external_lines:
        external_lines.append('# dir = "/work/fixtures/erf"\n# sources = "external-src"')

    return CONFIG_TEMPLATE.format(
        worktree=worktree,
        authors_line=authors_line,
        config_storage=config_storage,
        config_project=config_project,
        extension_sections=extension_sections,
        external_lines="\n".join(external_lines),
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
    data["external_dir"] = _ask(
        "каталог с .erf/.epf (v8unpack-исходники, пусто = пропустить)",
        DEFAULTS["external_dir"],
    )
    data["external_sources"] = _ask(
        "каталог исходников в worktree", DEFAULTS["external_sources"]
    )
    data["external_xml_dir"] = _ask(
        "каталог XML внешних обработок (EDT-проект, пусто = пропустить)", ""
    )
    if data["external_xml_dir"]:
        data["external_project"] = _ask(
            "имя EDT-проекта внешних обработок", DEFAULTS["external_project"]
        )
        data["external_base_project"] = _ask(
            "базовый проект (EDT)", data["config_project"]
        )
    return data


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>1c-convert — sync.toml</title>
<style>
 body{font-family:sans-serif;max-width:860px;margin:24px auto;padding:0 12px;background:#f6f7f9}
 h1{font-size:1.3rem} fieldset{margin:12px 0;border:1px solid #ccd;border-radius:8px;background:#fff}
 legend{font-weight:600;padding:0 6px}
 label{display:block;margin:6px 0 2px;font-size:.9rem;color:#333}
 input{width:100%;box-sizing:border-box;padding:6px;border:1px solid #bbc;border-radius:4px}
 .ext{border-left:4px solid #7aa;padding:6px 10px;margin:8px 0;background:#eef}
 button{margin-top:10px;padding:8px 16px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer}
 button.mini{background:#9333ea;padding:4px 10px}
 pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;overflow:auto}
 .hint{color:#777;font-size:.85rem}
</style></head><body>
<h1>1c-convert — конфигурация синхронизации (sync.toml)</h1>
<p class="hint">Пути указываются внутри контейнера. «Сохранить» записывает файл на сервере контейнера.</p>
<form id="f">
<fieldset><legend>Монорепозиторий</legend>
 <label>git-worktree <input name="worktree" value="/work/output/storage-git"></label>
 <label>Файл авторов <input name="authors_file" placeholder="/work/authors.txt"></label>
 <label>Домен email <input name="domain" value="storage.local"></label>
</fieldset>
<fieldset><legend>Хранилище конфигурации</legend>
 <label>Путь к хранилищу <input name="config_storage" value="/work/fixtures/crs/cf"></label>
 <label>Имя проекта <input name="config_project" value="configuration"></label>
</fieldset>
<fieldset><legend>Расширения</legend><div id="exts"></div>
 <button type="button" class="mini" onclick="addExt()">+ расширение</button>
</fieldset>
<fieldset><legend>Внешние отчёты и обработки</legend>
 <label>Каталог .erf/.epf <input name="external_dir" value="/work/fixtures/erf"></label>
 <label>Каталог исходников в worktree <input name="external_sources" value="external-src"></label>
 <label>Каталог XML (EDT-проект; пусто = пропустить) <input name="external_xml_dir"></label>
 <label>Имя EDT-проекта <input name="external_project" value="external"></label>
 <label>Базовый проект (EDT) <input name="external_base_project" value="configuration"></label>
</fieldset>
<button type="button" onclick="send(false)">Предпросмотр</button>
<button type="button" onclick="send(true)">Сохранить в файл</button>
</form>
<h2>sync.toml</h2><pre id="out">— заполните форму и нажмите «Предпросмотр» —</pre>
<script>
function addExt(){
 const d=document.createElement('div');d.className='ext';
 d.innerHTML='<label>Имя <input name="ext_name"></label>'
  +'<label>Хранилище <input name="ext_storage"></label>'
  +'<label>Проект <input name="ext_project"></label>'
  +'<label>Базовый проект (EDT) <input name="ext_base"></label>';
 document.getElementById('exts').appendChild(d);
}
async function send(save){
 const f=document.getElementById('f'), data=Object.fromEntries(new FormData(f));
 data.extensions=[...document.querySelectorAll('.ext')].map(e=>({
  name:e.querySelector('[name=ext_name]').value,
  storage:e.querySelector('[name=ext_storage]').value,
  project:e.querySelector('[name=ext_project]').value,
  base_project:e.querySelector('[name=ext_base]').value||data.config_project
 }));
 const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({save:!!save,data:data})});
 const j=await r.json();
 document.getElementById('out').textContent=j.toml||j.error;
}
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

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/generate":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            toml = render_toml(payload.get("data") or {})
        except Exception as error:
            self._send(400, json.dumps({"error": str(error)}).encode(), "application/json")
            return
        saved = ""
        if payload.get("save"):
            try:
                self.out_path.write_text(toml, encoding="utf-8")
                saved = f"\n# сохранено: {self.out_path}"
                info(f"config-server: saved {self.out_path}")
            except OSError as error:
                saved = f"\n# ошибка сохранения: {html.escape(str(error))}"
        self._send(
            200, json.dumps({"toml": toml + saved}).encode("utf-8"), "application/json"
        )


def serve(host: str, port: int, out_path: Path | None = None) -> None:
    if out_path is not None:
        Handler.out_path = out_path
    server = ThreadingHTTPServer((host, port), Handler)
    info(f"config-server: http://{host}:{port}/ -> пишет {Handler.out_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        info("config-server: stopped")
