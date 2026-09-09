# vendor/ — официальные дистрибутивы 1С

Каталог для локально скачанных официальных Linux-дистрибутивов.
Файлы **не коммитятся** (в `.gitignore`), **не публикуются** и
**не включаются в release**; в docker-образ они попадают только через
BuildKit named context и остаются в installer-стадиях (в финальный слой
копируются уже установленные каталоги).

## vendor/platform/

Платформа 1С:Предприятие 8.3 (нужен только серверный компонент с `ibcmd`).
Скачать с https://releases.1c.ru/project/Platform83 (нужна учётная запись ИТС).
Любой из вариантов:

| Вариант | Файл | Что внутри |
|---|---|---|
| 1 (рекомендуется) | `deb64_8_3_27_XXXX.zip` | deb-пакеты `1c-enterprise*-common/-server(-nls)_*.deb` |
| 2 | `server64_8_3_27_XXXX.zip` или `server64_with_all_clients_*.zip` | `setup-full-8.3.27.XXXX-x86_64.run` |

Толстый клиент (1cv8 DESIGNER) **не нужен** — конвертация выполняется `ibcmd`.

## vendor/edt/

1C:EDT offline-дистрибутив для Linux x86_64:
`1c_edt_distr_offline_<версия>_linux_x86_64.tar.gz`.
Скачать с https://releases.1c.ru/project/DevelopmentTools10.

## Версии

Версии платформы и EDT не зашиты в код. Фактические версии определяются
автоматически по установленным каталогам (`/opt/1cv8/current`,
`/opt/1C/1CE/components/1cedtcli`). В `.env` задаются только
метки для тега docker-образа и версия platform-support EDT, которую
нужно оставить в образе (`EDT_PLATFORM_SUPPORT`, например `8.3.27`).

## Проверка

```
vendor/
├── platform/
│   └── deb64_8_3_27_2342.zip
└── edt/
    └── 1c_edt_distr_offline_2026.1.3_25_linux_x86_64.tar.gz
```

Дальше: `docker compose build converter`.
