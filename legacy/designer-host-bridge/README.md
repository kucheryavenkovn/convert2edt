# crs2edt: хранилище конфигурации 1С → gitsync → ibcmd → EDT → Git/Gitea monorepo

Docker-стек однонаправленной синхронизации файлового хранилища конфигурации 1С
в существующий Git monorepo. В Git попадает **проект в формате EDT**; 1 версия
хранилища = 1 коммит с оригинальными автором/датой/комментарием; обновляется
только заданный `PROJECT_PATH` (например `configuration/main`).

```
E:\crs\gitsync  (/storage, ro)     — файловое хранилище 1С (SOURCE)
        ↓
1cv8 DESIGNER headless             — версии хранилища, временная ИБ (лицензия из volume)
        ↓
gitsync 3.8.0 + gitsync-plugins    — история, авторы, коммиты
        ↓
ibcmd (use-ibcmd)                  — выгрузка в XML
        ↓
edtExport + 1cedtcli (EDT 2026.2)  — XML → EDT-проект
        ↓
/repo/${PROJECT_PATH}              — служебный clone monorepo
        ↓
git push → Gitea
```

**Документы:**
- [docs/SPEC.md](docs/SPEC.md) — спецификация архитектуры (основной трек + альтернативный Host Bridge);
- [docs/research/](docs/research/) — зафиксированные исследования gitsync, gitsync-plugins,
  kafka-tools, edtfind/v8find, mussolene/1c-develop (все решения приняты по исходникам, не по статьям).

Основные компоненты и их назначение:

| Компонент | Для чего |
|---|---|
| `1cv8` (толстый клиент) | gitsync читает хранилище **только** конфигуратором: `/ConfigurationRepositoryReport`, `/ConfigurationRepositoryUpdateCfg`; создаёт временную ИБ |
| `ibcmd` | выгрузка конфигурации ИБ в XML (плагин `use-ibcmd`, заменяет `/DumpConfigToFiles`) |
| `1cedtcli` | headless-конвертация XML → EDT-проект (плагин `edtExport`) |
| OneScript 1.9.3 + gitsync 3.8.0 | движок синхронизации (CI gitsync — на OneScript 1.9.2, поэтому 2.x не используем) |

Базовый образ — десктоп-слой [mussolene/1c-develop](https://github.com/mussolene/1c-develop)
(Xfce/Xvnc/s6, механизм лицензирования `/var/1C/licenses`); платформа 8.3.27 и EDT
ставятся нашим слоем (готового образа 8.3.27 у 1c-develop нет — только 8.5.x).

---

## 1. Требования

- Windows-хост: Docker Desktop (WSL2), Docker 23+, Compose v2;
- доступ к `E:\crs\gitsync` (хранилище) и к Gitea (ssh);
- дистрибутивы 1С (платформа 8.3.27 + EDT offline) — см. [distr/README.md](distr/README.md);
- учётная запись developer.1c.ru для активации Developer License (один раз).

## 2. Установка (чистый сервер)

```powershell
git clone <converter-repo>; cd crs2edt
cp .env.example .env          # заполнить GIT_REMOTE, PROJECT_PATH, PLATFORM_VERSION, EDT_VERSION
mkdir .secrets
# пароль хранилища 1С (если нет — пустой файл):
Set-Content .secrets\storage_password "пароль"
# приватный ssh-ключ с доступом к Gitea:
Copy-Item ~\.ssh\id_ed25519 .secrets\git_ssh_key

# дистрибутивы в distr\ (см. distr/README.md)
docker volume create onec-license-store   # внешний volume с лицензией, НЕ удалять при down
docker compose build
```

## 3. Первичная активация Developer License (один раз)

```powershell
docker compose --profile license-ui up -d license-ui
```

Открыть VNC: `127.0.0.1:5900` (без пароля — поэтому порт слушает только localhost).
В Xfce стартует UI 1С (если нет — `docker exec -d -u usr1cv8 -e DISPLAY=:0 license-ui /opt/1cv8/current/1cv8c`).
Активировать **Developer License** через свой аккаунт developer.1c.ru (штатный механизм).
Файлы лицензии появятся в volume `onec-license-store` (`/var/1C/licenses`) — они переживают
restart/recreate/down-up. Проверить и остановить GUI:

```powershell
docker compose run --rm converter doctor     # [PASS] license + smoke test
docker compose --profile license-ui stop license-ui
```

Альтернатива — сетевой HASP: `NETHASP_INI_PATH` в `.env` + раскомментировать маунт в compose.

> **Важно**: `hostname` и `mac_address` контейнеров фиксированы в compose — программная лицензия
> привязывается к параметрам окружения. Не менять после активации.

## 4. Диагностика / миграция / синхронизация

```powershell
docker compose run --rm converter doctor    # платформа, лицензия (реальный smoke), EDT, git, storage, PROJECT_PATH
docker compose run --rm converter migrate   # вся история (батчами по MIGRATE_BATCH_LIMIT=500 версий)
docker compose run --rm converter sync      # только новые версии; без новых — 0 коммитов
```

После каждого батча: проверка `git diff --name-only` — изменения строго внутри
`PROJECT_PATH`, иначе push отменяется (критическая ошибка). Промежуточные XML/ИБ/EDT-workspace
живут в `/cache` (volume) и не коммитятся.

В monorepo в `PROJECT_PATH` попадают: EDT-проект + служебные `VERSION` и `AUTHORS`
(штатное поведение gitsync — пути к ним переназначить нельзя, см. docs/research/01 п.3).

### AUTHORS

`config/AUTHORS` (из `config/AUTHORS.example`): `ИмяВХранилище=Имя Фамилия <email>`.
Неизвестный автор → плагин `check-authors` **блокирует** sync и печатает точное имя
из хранилища. Случайные email не подставляются.

### Recovery

Падение на версии N (EDT-ошибка, обрыв и т.п.) → файл `VERSION` в WORKDIR откатывается
штатно; повторный `sync` продолжит с N. Если коммит создан, а push упал — повторный запуск
не создаст второй коммит той же версии (`sync` видит версию как синхронизированную).

## 5. Обновление релиза платформы/EDT

1. Новые дистрибутивы → `distr/` (старые удалить).
2. `PLATFORM_VERSION` / `EDT_VERSION` в `.env`.
3. `docker compose build` → `docker compose run --rm converter doctor` → `sync`.
Лицензия и служебные volumes (`repo-cache`, `converter-cache`) не затрагиваются.
`docker compose down -v` не удаляет `onec-license-store` (volume external), но сотрёт
служебные volumes — без необходимости не использовать.

## 6. Структура

```
Dockerfile                  # образ на базе mussolene/linux-desktop-base (8.3.27 + EDT + gitsync)
docker-compose.yml          # license-ui (VNC, активация) + converter (headless)
docker/scripts/             # install-platform.sh, install-edt.sh (сборка образа)
docker/rootfs/              # s6-сервис onec (license-ui режим)
scripts/                    # entrypoint + lib + doctor/migrate/sync
config/AUTHORS.example
distr/                      # закрытые дистрибутивы (не в git, не в образ)
docs/SPEC.md                # СПЕКА: архитектура, альтернативный Host Bridge
docs/research/              # исследования (gitsync, plugins, kafka-tools, edtfind, 1c-develop)
```

## 7. Частые проблемы

| Симптом | Причина/решение |
|---|---|
| doctor: `платформа младше версии хранилища` | пересобрать образ с платформой ≥ версии из `/storage/ver` |
| doctor: licensing smoke FAIL | лицензия не активирована/невалидна → license-ui; проверить hostname/mac_address не менялись |
| `хранилище обрезали` (gitsync) | VERSION в WORKDIR больше максимума хранилища — проверить repo-cache/историю |
| неизвестный автор | добавить в `config/AUTHORS`, повторить `sync` |
| изменения вне PROJECT_PATH | критическая ошибка конвейера; смотреть `git -C /repo log`, исправлять источник |
| push отклонён (non-fast-forward) | кто-то переписал ветку — вручную разобраться, force-push конвейер не делает |
