# SPEC: Синхронизация хранилища конфигурации 1С → Git/Gitea monorepo (EDT-формат)

**Статус:** в реализации. Версия спеки: 1.0 (2026-09-09).
**Владелец:** команда ERP CI. Документ обязателен к прочтению перед изменением архитектуры.

## 0. Содержание

1. Цель и конвейер
2. Исходные условия и ограничения
3. Вариант A (основной, реализуемый сейчас): Docker-стек на базе mussolene/1c-develop
4. Вариант B (альтернативный, отложенный): Windows Host Bridge
5. Сравнение вариантов и критерии выбора
6. Общие правила для обоих вариантов (monorepo, gitsync, VERSION/AUTHORS, изоляция)
7. Этапы, статус, открытые вопросы

---

## 1. Цель и конвейер

Однонаправленная синхронизация (без обратной записи Git → хранилище):

```
E:\crs\gitsync                        файловое хранилище 1С (SOURCE, только чтение)
        ↓
1cv8 DESIGNER (batch)                 получение версии N хранилища, загрузка во временную ИБ
        ↓
gitsync 3.8.0 + gitsync-plugins       движок: история версий, авторы, даты, коммиты
        ↓
ibcmd (use-ibcmd)                     выгрузка конфигурации в XML (вместо /DumpConfigToFiles)
        ↓
edtExport + 1cedtcli                  XML → проект EDT
        ↓
/repo/${PROJECT_PATH}                 единственный обновляемый каталог monorepo
        ↓
git commit (1 версия хранилища = 1 коммит, автор/дата/комментарий сохранены)
        ↓
git push → Gitea
```

Результат в monorepo — только EDT-проект. Промежуточные XML/ИБ/workspace не коммитятся.

## 2. Исходные условия и ограничения

- Windows-хост, Docker Desktop (WSL2), Docker 29.x, Compose v5.
- Хранилище: `E:\crs\gitsync` (формат создан платформой 8.3.27.2325 — файл `ver`: `{0,2,8,3,27,2325,"Designer"}`).
- Платформа в контейнере: **8.3.27.x** (≥ 2325). Версия хранилища ≠ версия платформы: gitsync/v8storage файл `ver` не читают, совместимость отдаётся платформе; платформа младше версии хранилища упадёт с ошибкой самой 1С (см. docs/research/04, п.4).
- EDT: 2026.2.0 (offline Linux-дистрибутив; в образе оставляем platform-support только 8.3.27).
- Целевой git — существующий monorepo; обновлять только `PROJECT_PATH` (например `configuration/main`); вложенный `.git` запрещён.
- Секреты (пароль хранилища, SSH-ключ, токены) — только через Docker secrets/`.secrets/`, никогда в Git/образ.
- Лицензия 1С — только штатные механизмы (см. ниже), никаких обходов.

## 3. Вариант A (основной): Docker-стек на базе mussolene/1c-develop

### 3.1 Принцип

Платформа 1С, конфигуратор и лицензирование живут ВНУТРИ Docker. Берём готовую
инфраструктуру `mussolene/1c-develop` (docs/research/06): базовый образ
`ghcr.io/mussolene/linux-desktop-base:bookworm` (Xfce + Xvnc + xrdp + s6 + шрифты + ru_RU),
поверх ставим платформу 8.3.27, OneScript 1.9.3, gitsync + plugins, EDT/1cedtcli, git/ssh.

Готового образа 1c-developer с 8.3.27 в ghcr НЕТ (только 8.5.x) — платформенный слой
собираем сами (их client/Dockerfile полностью параметризован, nick `Platform83` поддержан).
Менять целевую платформу на 8.5 ради чужого тега запрещено.

### 3.2 Два режима, один образ

```
onec-license-store (external volume, НЕ удалять при down)
        │  /var/1C/licenses  (root:grp1cv8, 775)
        │
   ┌────┴─────────────┐
   │                  │
license-ui        converter
(редко:           (основной,
 активация)        headless)
   │                  │
ONEC_RUNTIME_MODE   entrypoint.sh → gosu usr1cv8
=license-ui        doctor | migrate | sync
Xvnc :0 + Xfce     1cv8 DESIGNER batch (GUI не нужен)
127.0.0.1:5900     gitsync → ibcmd → 1cedtcli → git
```

Оба сервиса: одинаковый фиксированный `hostname` (и по необходимости `mac_address`) —
программная лицензия 1С привязывается к параметрам окружения; identity должна быть стабильна
между активацией и работой converter.

### 3.3 Лицензирование (штатное, без обхода)

1. Один раз: `docker compose --profile license-ui up -d license-ui`;
   VNC `127.0.0.1:5900` (пароля нет — потому порт только на localhost);
   запуск UI 1С: `ONEC_RUNTIME_MODE=license-ui` (их s6-сервис сам стартует `1cv8c` от usr1cv8)
   или `docker exec -d -u usr1cv8 -e DISPLAY=:0 license-ui /opt/1cv8/current/1cv8c`.
2. В UI: штатная активация Developer License через аккаунт developer.1c.ru.
3. Файлы лицензии появляются в `/var/1C/licenses` (volume). В лог не выводить, в Git/образ не копировать.
4. `docker compose stop license-ui`. Дальше всё headless.
5. Обязательный тест (п. 3.6): лицензия переживает restart/recreate/down-up (volume external;
   `down -v` НЕ использовать — предупредить в README).
6. Альтернатива без GUI-активации в контейнере: сетевой HASP — ro-маунт `nethasp.ini`
   в `/opt/1cv8/conf/nethasp.ini` (механизм 1c-develop, env `NETHASP_INI_PATH`). Основной PoC — software license.

### 3.4 Состав образа converter

| Компонент | Зачем | Источник |
|---|---|---|
| `1cv8` (толстый клиент) | gitsync читает хранилище ТОЛЬКО конфигуратором: `/ConfigurationRepositoryReport`, `/ConfigurationRepositoryUpdateCfg`; создаёт временную ИБ | 8.3.27, дистрибутив пользователя |
| `ibcmd` (+rac) | выгрузка XML (use-ibcmd), в `/opt/1cv8/x86_64/<ver>` рядом с 1cv8 | там же (server-компонент) |
| OneScript 1.9.3 | runtime gitsync (CI gitsync = 1.9.2; 2.x из 1c-develop не гарантирован) | deb с oscript.io |
| gitsync 3.8.0 + gitsync-plugins 2.0.3 | движок синхронизации; plugins: use-ibcmd, edtExport, limit, check-authors | `opm install` |
| EDT 2026.2.0 + 1cedtcli + OpenJDK 17 | XML→EDT (edtExport). EDT в `/opt/1C/1CE/components/1c-edt-*` (маркеры 1cedt/1cedtcli для edtfind, без ring) | offline-дистрибутив пользователя |
| git, openssh-client | служебный clone, push | apt |

Пути платформы/EDT обязательно соответствуют автопоиску v8find/edtfind (docs/research/04).

### 3.5 Runtime workflow (converter)

```
entrypoint.sh (root): права на volumes, ssh-key из секрета → gosu usr1cv8
  doctor  | migrate | sync | help
sync:
  1. repo_prepare: clone или fetch+checkout+pull --ff-only в /repo (volume repo-cache)
  2. ensure_workdir: /repo/$PROJECT_PATH внутри /repo, вложенного .git нет
  3. если нет VERSION → gitsync init; AUTHORS из /config/AUTHORS поверх
  4. HEAD_before = rev-parse HEAD
  5. gitsync sync --disable-auto-src /storage /repo/$PROJECT_PATH
     (env GITSYNC_*: storage user/pwd, V8VERSION=8.3, EDT_VERSION, IBCMD_*, TEMP=/cache/...)
  6. HEAD_after; 0 новых версий → 0 коммитов → выход
  7. check_isolation: git diff --name-only before..after — всё внутри $PROJECT_PATH, иначе FAIL
  8. verify_edt_project: маркеры DT-INF/PROJECT.PMF, .project, src/
  9. git push origin $GIT_BRANCH
migrate = цикл sync с GITSYNC_LIMIT (батчи, push после каждого)
```

Известные особенности gitsync (подробно docs/research/01,02):
- `AUTHORS` и `VERSION` лежат в WORKDIR и коммитятся вместе с проектом — штатно, переназначить нельзя;
  VERSION — XML `<VERSION>N</VERSION>`; AUTHORS — ini `ИмяВХранилище=Имя <email>`;
- WORKDIR полностью очищается при каждой версии (белый список: .git*, AUTHORS, VERSION) →
  в PROJECT_PATH не должно быть ничего постороннего;
- WORKDIR-подкаталог monorepo поддержан: `init` не создаёт вложенный `.git` (проверяет
  `git rev-parse` вверх по дереву); `--disable-auto-src` обязателен (EDT-проект содержит `src/`);
- unknown автор → check-authors блокирует синхронизацию с точным именем (не подставляем случайные данные);
- recovery: VERSION откатывается при ошибке → повтор с прерванной версии; повторный запуск
  без новых версий = 0 коммитов.

### 3.6 Doctor (container)

```
[PASS] oscript / gitsync / plugins(enabled) / git / ssh
[PASS] 1cv8 executable + версия ≥ версии хранилища (файл /storage/ver)
[PASS] ibcmd executable
[PASS] 1cedtcli (-command version) / java
[PASS] /var/1C/licenses mounted + файлы лицензии есть
[PASS] 1C runtime licensing smoke test   ← реальный запуск 1cv8 (создание временной ИБ)
[PASS] storage available (ver читается, платформа совместима)
[PASS] Git remote available (ls-remote)
[PASS] PROJECT_PATH valid (внутри /repo, без вложенного .git)
```

Тесты сохранности лицензии (фиксируются в отчёте): smoke → `docker restart` → down/up →
recreate без удаления volume. Платформа: Windows + Docker Desktop + WSL2.

### 3.7 Compose (каркас)

```yaml
services:
  license-ui:            # profile license-ui; image тот же; entrypoint /init (s6);
    hostname: onec-gitsync        # ONEC_RUNTIME_MODE=license-ui; ports 127.0.0.1:5900:5900
    volumes: [onec-license-store:/var/1C/licenses]
  converter:             # image тот же; entrypoint наш; run --rm
    hostname: onec-gitsync
    environment: STORAGE_PATH=/storage, GIT_REMOTE, GIT_BRANCH, PROJECT_PATH, ...
    volumes: onec-license-store:/var/1C/licenses, E:/crs/gitsync:/storage:ro,
             repo-cache:/repo, converter-cache:/cache, ./config:/config:ro
    secrets: [storage_password, git_ssh_key]
volumes: { onec-license-store: {external: true}, repo-cache: {}, converter-cache: {} }
```

`.env`: `PLATFORM_VERSION=8.3.27.xxxx`, `EDT_VERSION=2026.2.0`, `GITSYNC_VERSION=3.8.0`,
`OSCRIPT_VERSION=1.9.3`, `GIT_REMOTE/GIT_BRANCH/PROJECT_PATH`, `IBCMD_THREADS`, `INCREMENTAL`,
`MIGRATE_BATCH_LIMIT`, `STORAGE_HOST_PATH=E:/crs/gitsync`.

### 3.8 Обновление релиза (прозрачность для разработчика)

Новый релиз платформы/EDT: положить новые дистрибутивы в `./distr`, поправить версии в `.env`,
`docker compose build`, `docker compose run --rm converter doctor`, `docker compose run --rm converter sync`.
Всё версионировано ARG'ами; каталоги установки не меняются (автопоиск v8find/edtfind).

## 4. Вариант B (отложенный): Windows Host Bridge

**Статус: спроектирован, НЕ реализуется сейчас.** Зафиксирован, чтобы не потерять.
Имеет смысл в гомогенной среде (Linux CI, много машин без Docker Desktop, нельзя/не хочется
активировать лицензию в контейнере, лицензия уже есть на Windows-хосте).

### 4.1 Идея

Платформа 1С остаётся на Windows (уже установлена и лицензирована). Docker обращается к ней
через узкий allowlisted HTTP-сервис (Host Bridge). В контейнере gitsync работает с wrapper'ом
`/usr/local/bin/1cv8-host`, который для gitsync неотличим от обычного `1cv8`.

```
Docker: gitsync → 1cv8-host (wrapper) → HTTP → Windows Host Bridge → 1cv8.exe DESIGNER (штатная лицензия)
   ↓ shared staging /bridge = E:\1c-bridge (jobs, временные ИБ, XML)
ibcmd + 1cedtcli → EDT → git (всё внутри Docker)
```

Ключевая техническая возможность (проверено по исходникам, docs/research/01):
gitsync позволяет указать произвольный executable — `--v8-path` / env `GITSYNC_V8_PATH`.
Форк gitsync не требуется. Wrapper перехватывает argv, мапит пути (явная таблица
`/bridge → E:\1c-bridge`, `/storage → E:\crs\gitsync`), дергает bridge, возвращает exit code.

### 4.2 Host Bridge API (минимальный)

```
GET  /health          → {status, platform, licenseCheck, storageAccess}  (licenseCheck = smoke test)
GET  /platforms       → список установленных платформ (C:\Program Files\1cv8\8.3.xx.xxxx\bin\1cv8.exe)
POST /designer/run    → синхронный запуск ТОЛЬКО 1cv8.exe DESIGNER с allowlisted ключами
```

Жёсткие ограничения:
- только `1cv8.exe`, только режим DESIGNER; валидация ключей по белому списку
  (CREATEINFOBASE, /F, /N, /P, /Out, /ConfigurationRepositoryF|N|P|Report|UpdateCfg,
  /DumpConfigToFiles(+listFile), -NBegin, -NEnd, -force, -IncludeCommentLinesWithDoubleSlash, -ReportFormat, ...);
- никаких произвольных exe / shell / cmd / powershell / `&|>`; CreateProcess со структурным массивом аргументов;
- allowlist корней хранилищ (`allowedStorages: [E:\crs\gitsync]`) и фиксированный bridge root `E:\1c-bridge`
  (никаких путей Docker'а вне mapping-таблицы, защита от `..\`, `C:\Windows`, UNC);
- bearer token; bind `127.0.0.1` (доступ из Docker через `host.docker.internal`);
- timeout на job (убивать зависший 1cv8, сохранять diagnostic log), `MAX_CONCURRENT_JOBS=1`;
- логи: jobId/операция/платформа/exitCode/duration; пароли маскировать (`/P ****`), токен не логировать.

### 4.3 Milestones (если решим реализовывать)

1. Docker → wrapper → bridge → 1cv8 DESIGNER → exitCode=0 (минимальный вызов).
2. gitsync без форка: repository read, получение одной версии хранилища.
   (Требуется дорезёрч: полный перечень фактических вызовов 1cv8 из v8runner/v8storage/gitsync
   и определение версии платформы при `--v8-path` — иначе wrapper не угадает формат вызова.)
3. use-ibcmd (Linux ibcmd поверх временной ИБ из staging; совместимость версий!) + edtExport.
4. 5–10 версий, авторы/даты/комментарии; incremental; recovery.
5. install-service.ps1/doctor.ps1 (Windows-сторона), service account `svc_1c_git` с доступом
   к лицензии и хранилищу; failure-mode тесты (bridge offline, timeout, license, storage...).

Риски варианта B: лицензия в пользовательском контекне Windows (сервис-аккаунт должен видеть ту же
лицензию); версия Linux ibcmd должна совпадать по сборке с Windows 1cv8 (одна файловая ИБ);
диалект CLI конфигуратора между сборками; Windows-машина как SPOF.

## 5. Сравнение

| Критерий | A: 1c-develop Docker | B: Host Bridge |
|---|---|---|
| Готовность к реализации | высок (всё в одном образе, всё локально) | сред (свой daemon + wrapper + сервис) |
| Лицензия | активация в контейнере (один раз, VNC), риск привязки к identity контейнера | уже существующая на Windows |
| Гомогенность/масштаб | образ переносим, но активация на каждой среде | привязка к Windows-хосту |
| Обслуживаемость | один образ, стандартный compose | + Windows Service, сервис-аккаунт, API |
| Безопасность | стандартный Docker-контур | attack surface HTTP-API на хосте (нужен жёсткий allowlist) |
| Обновление релизов | пересборка слоя из дистрибутива | обновление платформы на Windows |

Выбран вариант A. Вариант B остаётся запасным для Linux-центричных сред.

## 6. Общие правила (обязательны в обоих вариантах)

1. Только один git-репозиторий (`project-root/.git`), `PROJECT_PATH` — просто каталог.
2. Изменения только внутри `PROJECT_PATH/**` (проверка diff перед push; при нарушении — FAIL).
3. `VERSION`/`AUTHORS` — штатно в WORKDIR (переназначение не поддерживается gitsync), коммитятся; это документировано.
4. Не форкать gitsync; не писать свой XML→EDT; не читать формат хранилища напрямую.
5. 1 версия хранилища = 1 коммит; автор/дата/комментарий из хранилища; force-push запрещён.
6. Секреты — Docker secrets; `.secrets/` и `distr/` в .gitignore.
7. Повторный sync без новых версий — 0 коммитов; падение на версии N → продолжение с N.
8. Хранилище монтируется read-only.

## 7. Статус и открытые вопросы

- Исследования зафиксированы: docs/research/01 (gitsync), 02 (plugins), 03 (kafka-tools),
  04 (edtfind/v8find/формат хранилища), 06 (1c-develop).
- В реализации: вариант A. Этапы по фазам (license PoC → repository PoC → gitsync → ibcmd → EDT → monorepo → production).
- Открытые вопросы:
  - [ ] совместимость gitsync 3.8.0 c OneScript 2.x (пока ставим 1.9.3);
  - [ ] стабильность software license при recreate контейнера (hostname/mac_address) — проверить на Phase 2;
  - [ ] EDT 2026.2.0 + platform-support 8.3.27 — проверить после сборки (1cedtcli -command platform-versions);
  - [ ] реально ли `/storage:ro` для конфигуратора (lock-файлы .cfl) — если нет, fallback: копия хранилища в cache-volume;
  - [ ] производительность полной EDT-конвертации на каждою версию при миграции 18000+ версий (батчи limit, замеры).
